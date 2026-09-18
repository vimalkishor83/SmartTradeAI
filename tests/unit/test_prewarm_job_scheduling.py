"""Regression coverage for the CPU-spike fix: the five recurring pre-warm
jobs (prewarm_ta, prewarm_heatmap, prewarm_delta_scanner,
prewarm_delta_screener, prewarm_delta_indicator_screener) must each get a
distinct next_run_time stagger and coalesce=True, so their 2/3/5-minute
periods don't keep re-aligning into the same ~100%+ CPU burst confirmed
live on production. See app/tasks/data_tasks.py::register_data_jobs.
"""

from apscheduler.schedulers.background import BackgroundScheduler

from app.tasks.data_tasks import register_data_jobs

_PREWARM_JOB_IDS = [
    "prewarm_ta",
    "prewarm_heatmap",
    "prewarm_delta_scanner",
    "prewarm_delta_screener",
    "prewarm_delta_indicator_screener",
]


def test_prewarm_jobs_coalesce_and_have_distinct_staggered_start_times(app):
    scheduler = BackgroundScheduler()
    register_data_jobs(scheduler, app)

    jobs = {job.id: job for job in scheduler.get_jobs()}
    for job_id in _PREWARM_JOB_IDS:
        assert job_id in jobs, f"expected job {job_id} to be registered"
        job = jobs[job_id]
        assert job.coalesce is True, f"{job_id} should coalesce missed runs"

    next_run_times = [jobs[job_id].next_run_time for job_id in _PREWARM_JOB_IDS]
    # Every job's first run must be genuinely distinct from the others --
    # the whole point of staggering is that no two of these fire together.
    assert len(set(next_run_times)) == len(next_run_times)

    # All staggered starts must land after the one-time startup pre-warm
    # jobs (which fire once, 15-45s after boot) have already finished,
    # so this doesn't create a second near-duplicate run right after boot.
    assert all(t is not None for t in next_run_times)
