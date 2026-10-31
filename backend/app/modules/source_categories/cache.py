"""Prevent caching both positive and negative source-category responses."""

from starlette.datastructures import MutableHeaders


def is_source_category_path(path: str) -> bool:
    prefix = "/api/v1/source-categories"
    return path == prefix or path.startswith(prefix + "/")


class SourceCategoryNoStoreMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or not is_source_category_path(path):
            await self.app(scope, receive, send)
            return

        async def send_no_store(message):
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, send_no_store)


def install_unexpected_error_no_store(application):
    # Starlette's ServerErrorMiddleware is outside user middleware. Delegate
    # to the existing sanitized handler and add the same policy to its 500.
    original = application.exception_handlers[Exception]

    async def handle(request, error):
        response = await original(request, error)
        if is_source_category_path(request.scope.get("path", "")):
            response.headers["Cache-Control"] = "no-store"
        return response

    application.add_exception_handler(Exception, handle)
