"""Task-function registry: Celery tasks and the thread-pool fallback mode share the same batch of task bodies."""


def _load():
    from app.tasks import index_tasks, parse_tasks, review_tasks  # noqa: F401

    return {
        "parse_contract": parse_tasks.parse_contract_impl,
        "run_review": review_tasks.run_review_impl,
        "index_law": index_tasks.index_law_impl,
    }


TASK_FUNCS = _load()
