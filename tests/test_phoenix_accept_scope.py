from phoenix_learn.accept import BeliefStore, VACUOUS, verify_gate


def test_verify_gate_is_failure_first_not_vacuous():
    assert verify_gate([True])["reason"] == VACUOUS
    verdict = verify_gate([False, True])
    assert verdict["ok"] is True
    assert verdict["saw_red"] is True
    assert verdict["green_after_red"] is True
    assert verdict["currently_green"] is True


def test_entering_new_scope_retires_established_claims():
    store = BeliefStore(scope="level-1")
    store.observe("drag exists", False, seed=1)
    store.observe("drag exists", True, seed=1)
    assert store.accept("drag exists")["ok"] is True

    dropped = store.enter("level-2")
    assert dropped == ["drag exists"]
    assert store.accept("drag exists")["ok"] is False
