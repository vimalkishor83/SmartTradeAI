def paginate_response(query, page: int, per_page: int = 20) -> dict:
    result = query.paginate(page=page, per_page=per_page, error_out=False)
    return {
        "items": result.items,
        "total": result.total,
        "page": page,
        "pages": result.pages,
        "per_page": per_page,
        "has_next": result.has_next,
        "has_prev": result.has_prev,
    }
