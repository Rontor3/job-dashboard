from career_agent.integrations.live_view.coords import norm_to_px


def test_center_and_corners():
    assert norm_to_px(0.5, 0.5, 400, 800) == (200, 400)
    assert norm_to_px(0.0, 0.0, 400, 800) == (0, 0)
    assert norm_to_px(1.0, 1.0, 400, 800) == (400, 800)


def test_clamps_out_of_range():
    assert norm_to_px(-1, 2, 400, 800) == (0, 800)
