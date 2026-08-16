//! `supervisor` — the bounded-concurrency ready queue at the heart of the mission supervisor.
//!
//! This is the smallest spine primitive of the durable supervisor: a pure, in-memory admission
//! controller. It admits at most `capacity` tasks concurrently and **defers** the rest in FIFO
//! order, so the same sequence of calls always produces the same schedule. No async runtime, no
//! git, no filesystem, no network — those layers ride on top of this decision, they are not part
//! of it. Keeping the ready queue pure is what makes the supervisor's scheduling testable and
//! reproducible instead of a timing-dependent guess.
//!
//! INVARIANT: `in_flight` never exceeds `capacity`. This is the one bound every other scheduling
//! decision rests on — [`crate::backend_select`] refuses rather than silently running locally
//! precisely so this cannot be broken from outside.
//! INVARIANT: deferred tasks are released in FIFO order, so the same call sequence always produces
//! the same schedule and a starved task cannot be starved twice for the same reason.
//! INVARIANT: a zero-capacity supervisor admits nothing, rather than admitting work it can never run.

use std::collections::VecDeque;

/// The supervisor's verdict for a single admission request.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Admission {
    /// A concurrency slot was free; the task is now in flight.
    Admitted,
    /// The supervisor is at capacity; the task was queued and will be released by `next_ready`.
    Deferred,
    /// Refused because a zero-capacity supervisor can never run any admitted work.
    RefusedZeroCapacity,
}

/// A deterministic, bounded-concurrency ready queue.
#[derive(Debug, Clone)]
pub struct Supervisor {
    capacity: usize,
    in_flight: Vec<String>,
    deferred: VecDeque<String>,
}

impl Supervisor {
    /// Build a supervisor that allows at most `capacity` tasks in flight at once.
    pub fn with_capacity(capacity: usize) -> Self {
        Self { capacity, in_flight: Vec::new(), deferred: VecDeque::new() }
    }

    /// The bounded concurrency limit.
    pub fn capacity(&self) -> usize {
        self.capacity
    }

    /// How many tasks currently hold a slot.
    pub fn in_flight(&self) -> usize {
        self.in_flight.len()
    }

    /// How many tasks are waiting for a slot.
    pub fn deferred(&self) -> usize {
        self.deferred.len()
    }

    /// Request a slot for `task`. Admits while under capacity, otherwise defers in FIFO order.
    pub fn admit(&mut self, task: &str) -> Admission {
        if self.capacity == 0 {
            return Admission::RefusedZeroCapacity;
        }
        if self.in_flight.iter().any(|queued| queued == task) {
            return Admission::Admitted;
        }
        if self.deferred.iter().any(|queued| queued == task) {
            return Admission::Deferred;
        }
        if self.in_flight.len() < self.capacity {
            self.in_flight.push(task.to_string());
            Admission::Admitted
        } else {
            self.deferred.push_back(task.to_string());
            Admission::Deferred
        }
    }

    /// Release the slot held by `task`. Returns false if it was not in flight.
    pub fn complete(&mut self, task: &str) -> bool {
        match self.in_flight.iter().position(|t| t == task) {
            Some(i) => {
                self.in_flight.remove(i);
                true
            }
            None => false,
        }
    }

    /// Remove `task` from either queue. Returns whether any queued state was withdrawn.
    pub fn withdraw(&mut self, task: &str) -> bool {
        if let Some(i) = self.in_flight.iter().position(|queued| queued == task) {
            self.in_flight.remove(i);
            return true;
        }
        if let Some(i) = self.deferred.iter().position(|queued| queued == task) {
            self.deferred.remove(i);
            return true;
        }
        false
    }

    /// Promote the oldest deferred task into a free slot, if there is one.
    pub fn next_ready(&mut self) -> Option<String> {
        if self.in_flight.len() >= self.capacity {
            return None;
        }
        let task = self.deferred.pop_front()?;
        self.in_flight.push(task.clone());
        Some(task)
    }
}

#[cfg(test)]
mod supervisor_tests {
    use super::*;

    #[test]
    fn supervisor_admits_up_to_capacity() {
        let mut s = Supervisor::with_capacity(2);
        assert_eq!(s.admit("a"), Admission::Admitted);
        assert_eq!(s.admit("b"), Admission::Admitted);
        assert_eq!(s.in_flight(), 2);
        assert_eq!(s.capacity(), 2);
    }

    #[test]
    fn supervisor_defers_when_at_capacity() {
        let mut s = Supervisor::with_capacity(1);
        assert_eq!(s.admit("a"), Admission::Admitted);
        assert_eq!(s.admit("b"), Admission::Deferred);
        assert_eq!(s.in_flight(), 1, "the bound must never be exceeded");
        assert_eq!(s.deferred(), 1);
    }

    #[test]
    fn supervisor_frees_slot_on_complete() {
        let mut s = Supervisor::with_capacity(1);
        assert_eq!(s.admit("a"), Admission::Admitted);
        assert!(s.complete("a"), "completing an in-flight task frees its slot");
        assert_eq!(s.in_flight(), 0);
        assert!(!s.complete("a"), "completing twice must not free a phantom slot");
        assert_eq!(s.admit("b"), Admission::Admitted);
    }

    #[test]
    fn supervisor_promotes_deferred_in_fifo_order() {
        let mut s = Supervisor::with_capacity(1);
        s.admit("a");
        s.admit("b");
        s.admit("c");
        assert_eq!(s.next_ready(), None, "no slot is free while `a` runs");

        s.complete("a");
        assert_eq!(s.next_ready(), Some("b".to_string()), "oldest deferred task runs first");
        assert_eq!(s.in_flight(), 1);
        assert_eq!(s.next_ready(), None, "the single slot is taken again");

        s.complete("b");
        assert_eq!(s.next_ready(), Some("c".to_string()));
        assert_eq!(s.deferred(), 0);
    }
}
