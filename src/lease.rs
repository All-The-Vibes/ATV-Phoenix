//! `lease` — goal leases with fencing tokens.
//!
//! The ready queue in [`crate::supervisor`] decides *what* runs next; leases decide *who owns it*
//! and, critically, whose writes are still allowed to land. A supervisor that only tracks ownership
//! is not restart-safe: a worker can stall past its lease, the goal gets handed to a replacement,
//! and then the zombie wakes up and commits stale work over the top of the new holder's.
//!
//! The fix is a **fencing token** — a strictly increasing `u64` minted on every grant. A holder
//! presents its token with each write; the registry rejects any token that is not the goal's current
//! lease, and refuses to move a goal's committed watermark backwards. The zombie is fenced out by
//! arithmetic rather than by hoping it noticed it lost the lease.
//!
//! Time is a caller-supplied logical clock (`now`), never the wall clock, so the same call sequence
//! always produces the same decisions — the same purity discipline the ready queue follows.
//!
//! INVARIANT: fencing tokens are strictly increasing across the registry's whole life, so a token
//! is never reissued and "which grant was this" is always answerable.
//! INVARIANT: a goal's committed watermark never moves backwards. This is what fences the zombie:
//! a stalled worker that wakes after handover presents an older token and is refused by arithmetic
//! rather than by hoping it noticed it lost the lease.
//! INVARIANT: a write presenting anything other than the goal's current unexpired lease is `Fenced`
//! and does not land.

use std::collections::BTreeMap;

/// The first fencing token ever minted. Tokens are strictly increasing from here.
pub const FIRST_TOKEN: u64 = 1;

/// An exclusive, time-bounded claim on one goal.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Lease {
    /// The goal this lease covers.
    pub goal: String,
    /// The worker holding the lease.
    pub holder: String,
    /// Strictly increasing fencing token minted at grant time.
    pub token: u64,
    /// Logical time at which the lease stops being valid.
    pub expires_at: u64,
}

/// Why a lease operation was refused.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LeaseDenied {
    /// Another holder owns an unexpired lease on this goal.
    Held,
    /// The presented token is not this goal's current, unexpired lease.
    Stale,
}

/// The verdict on a fenced write.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Fence {
    /// The token was current; the write may land and the watermark advanced.
    Accepted,
    /// The token was stale or superseded; the write must be discarded.
    Fenced,
}

/// Tracks goal ownership and the fencing watermark for each goal.
#[derive(Debug, Clone)]
pub struct LeaseRegistry {
    next_token: u64,
    active: BTreeMap<String, Lease>,
    committed: BTreeMap<String, u64>,
}

impl Default for LeaseRegistry {
    fn default() -> Self {
        Self::new()
    }
}

impl LeaseRegistry {
    /// An empty registry whose first grant mints [`FIRST_TOKEN`].
    pub fn new() -> Self {
        Self { next_token: FIRST_TOKEN, active: BTreeMap::new(), committed: BTreeMap::new() }
    }

    /// Claim `goal` for `holder` until `now + ttl`.
    ///
    /// Succeeds when the goal is unheld or its lease has expired at `now`. Every success mints a
    /// fresh token that is strictly greater than every token minted before it, across all goals.
    pub fn acquire(
        &mut self,
        goal: &str,
        holder: &str,
        now: u64,
        ttl: u64,
    ) -> Result<Lease, LeaseDenied> {
        if let Some(current) = self.active.get(goal) {
            if current.expires_at > now {
                return Err(LeaseDenied::Held);
            }
        }
        let token = self.next_token;
        self.next_token += 1;
        let lease = Lease {
            goal: goal.to_string(),
            holder: holder.to_string(),
            token,
            expires_at: now.saturating_add(ttl),
        };
        self.active.insert(goal.to_string(), lease.clone());
        Ok(lease)
    }

    /// Extend the current lease on `goal` to `now + ttl`.
    ///
    /// Only the holder of the current, unexpired token may renew — an expired holder must re-acquire
    /// and take a new token, so it can never silently reclaim ownership it already lost.
    pub fn renew(
        &mut self,
        goal: &str,
        token: u64,
        now: u64,
        ttl: u64,
    ) -> Result<Lease, LeaseDenied> {
        match self.active.get_mut(goal) {
            Some(current) if current.token == token && current.expires_at > now => {
                current.expires_at = now.saturating_add(ttl);
                Ok(current.clone())
            }
            _ => Err(LeaseDenied::Stale),
        }
    }

    /// Give up the lease on `goal`, freeing it for the next holder immediately.
    ///
    /// Returns `false` if `token` is not the goal's current lease, so a stale worker cannot release
    /// a lease it no longer owns out from under its replacement.
    pub fn release(&mut self, goal: &str, token: u64) -> bool {
        match self.active.get(goal) {
            Some(current) if current.token == token => {
                self.active.remove(goal);
                true
            }
            _ => false,
        }
    }

    /// The current lease on `goal`, whether or not it has expired.
    pub fn current(&self, goal: &str) -> Option<&Lease> {
        self.active.get(goal)
    }

    /// Whether `token` is the current, unexpired lease on `goal` at `now`.
    pub fn is_valid(&self, goal: &str, token: u64, now: u64) -> bool {
        matches!(self.active.get(goal), Some(c) if c.token == token && c.expires_at > now)
    }

    /// The highest token that has successfully committed against `goal`.
    pub fn watermark(&self, goal: &str) -> Option<u64> {
        self.committed.get(goal).copied()
    }

    /// Fence a write from `token` against `goal` at `now`.
    ///
    /// Accepted only when the token is the current unexpired lease **and** it does not move the
    /// goal's committed watermark backwards. Both guards must hold: the first stops a zombie whose
    /// lease was reassigned, the second keeps the watermark monotonic even if ownership rules are
    /// later relaxed.
    pub fn commit(&mut self, goal: &str, token: u64, now: u64) -> Fence {
        if !self.is_valid(goal, token, now) {
            return Fence::Fenced;
        }
        if let Some(high) = self.watermark(goal) {
            if token < high {
                return Fence::Fenced;
            }
        }
        self.committed.insert(goal.to_string(), token);
        Fence::Accepted
    }
}
