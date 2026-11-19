"""Keep concurrent responses from replaying a rotated username session cookie."""

from starlette.middleware.sessions import SessionMiddleware
from starlette.datastructures import MutableHeaders


class CredentialSessionMiddleware(SessionMiddleware):
    def __init__(self, app, **options):
        async def snapshot(scope, receive, send):
            if "credential_stamp" in scope.get("session", {}):
                scope["username_session"] = True
            await app(scope, receive, send)

        super().__init__(snapshot, **options)

    async def __call__(self, scope, receive, send):
        async def send_response(message):
            if (message["type"] == "http.response.start" and scope.get("username_session")
                    and not scope.get("write_session_cookie")):
                headers = MutableHeaders(scope=message)
                cookies = headers.getlist("set-cookie")
                if any(cookie.startswith(f"{self.session_cookie}=") for cookie in cookies):
                    del headers["set-cookie"]
                    for cookie in cookies:
                        if not cookie.startswith(f"{self.session_cookie}="):
                            headers.append("set-cookie", cookie)
            await send(message)

        await super().__call__(scope, receive, send_response)
