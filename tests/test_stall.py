from job_dashboard.apply.outcome import outcome
from job_dashboard.apply.stall import STALL_EXIT, progress_token, watch

LOG = ("[perc] frame 0: 'https://a.example/job'\n[fill] step 1: 3 filled, 2 escalated\n")


def test_progress_token_tracks_fills_pages_and_assist():
    t0 = progress_token(LOG)
    assert t0 == (3, 1, 0, 0, 0)
    assert progress_token(LOG + "[perc] snapshot: 0 fields\n") == t0                      # chatter is not progress
    assert progress_token(LOG + "[fill] step 2: 7 filled, 0 escalated\n")[0] == 7
    assert progress_token(LOG + "[perc] frame 0: 'https://b.example/apply'\n")[1] == 2
    assert progress_token(LOG + "[assist 1/5] Claude chose: click 'Next' — x\n")[2] == 1
    assert progress_token(LOG + "[assist 2/5] Claude chose: give_up — x\n")[2] == 0       # a give-up moved nothing


def _run(tmp_path, grow, alive_ticks, stall_s=600):
    log, clock, stopped = tmp_path / "r.log", [0.0], []
    log.write_text(LOG)
    ticks = iter(range(alive_ticks))

    def is_running():
        return next(ticks, None) is not None

    def sleep(s):
        clock[0] += 60
        if grow and clock[0] == 120:                               # real progress at t=2min
            log.write_text(LOG + "[fill] step 2: 9 filled, 0 escalated\n")
    r = watch(is_running, lambda: stopped.append(1), str(log), stall_s=stall_s, poll_s=60,
              clock=lambda: clock[0], sleep=sleep, say=lambda *a, **k: None)
    return r, stopped


def test_watch_stops_a_run_with_no_progress(tmp_path):
    stalled, stopped = _run(tmp_path, grow=False, alive_ticks=100)
    assert stalled and stopped == [1]


def test_progress_resets_the_clock_and_exit_is_not_a_stall(tmp_path):
    assert _run(tmp_path, grow=True, alive_ticks=11)[0] is False   # 11 min alive, but progress at 2 min
    assert _run(tmp_path, grow=False, alive_ticks=3)[0] is False   # exited on its own before 10 min


def test_stalled_run_is_parked_not_failed():
    assert outcome(None, STALL_EXIT) == ("parked", "stalled_no_progress", "failed")


def test_asking_the_human_and_their_answer_both_count_as_progress():
    base = "[fill] step 1: 14 filled, 3 escalated\n"
    asked = base + "[telegram] sending 3 field question(s) — waiting for reply...\n"
    answered = asked + "[human] got 3 answer(s) — applying\n"
    assert progress_token(base) != progress_token(asked) != progress_token(answered)
