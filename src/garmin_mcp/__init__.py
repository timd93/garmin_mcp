"""
Modular MCP Server for Garmin Connect Data
"""

import json
import os

import requests
from mcp.server.fastmcp import FastMCP

from garth.exc import GarthHTTPError
from garminconnect import Garmin, GarminConnectAuthenticationError


def _to_json_str(data):
    """Convert data to JSON string if it's not already a string"""
    if isinstance(data, str):
        return data
    try:
        return json.dumps(data, indent=2, default=str)
    except (TypeError, ValueError):
        return str(data)

# Import all modules
from garmin_mcp import activity_management
from garmin_mcp import health_wellness
from garmin_mcp import user_profile
from garmin_mcp import devices
from garmin_mcp import gear_management
from garmin_mcp import weight_management
from garmin_mcp import challenges
from garmin_mcp import training
from garmin_mcp import workouts
from garmin_mcp import data_management
from garmin_mcp import womens_health
from garmin_mcp import recommendations

def get_mfa() -> str:
    """Get MFA code non-interactively for container/Kubernetes environments.

    Sources (checked in order):
    - GARMIN_MFA_CODE env var
    - GARMIN_MFA_CODE_FILE pointing to a file containing the code
    - Poll for up to GARMIN_MFA_WAIT_SECONDS for either of the above to appear
    """
    print("\nGarmin Connect MFA required. Awaiting code via env or file...")

    mfa_code = os.environ.get("GARMIN_MFA_CODE")
    if mfa_code:
        return mfa_code.strip()

    mfa_file = os.environ.get("GARMIN_MFA_CODE_FILE")
    if mfa_file and os.path.exists(os.path.expanduser(mfa_file)):
        with open(os.path.expanduser(mfa_file), "r") as f:
            return f.read().strip()

    # Optional polling window to allow sidecar/secret updates
    wait_seconds = int(os.environ.get("GARMIN_MFA_WAIT_SECONDS", "0") or 0)
    if wait_seconds > 0:
        import time

        end_time = time.time() + wait_seconds
        while time.time() < end_time:
            mfa_code = os.environ.get("GARMIN_MFA_CODE")
            if mfa_code:
                return mfa_code.strip()

            mfa_file = os.environ.get("GARMIN_MFA_CODE_FILE")
            if mfa_file and os.path.exists(os.path.expanduser(mfa_file)):
                with open(os.path.expanduser(mfa_file), "r") as f:
                    return f.read().strip()

            time.sleep(1)

    # Fallback to interactive terminal input if running in an interactive session (e.g. docker run -it)
    import sys
    if sys.stdin.isatty():
        try:
            val = input("Enter Garmin Connect MFA Code: ").strip()
            if val:
                return val
        except Exception:
            pass

    raise RuntimeError(
        "MFA code required but not provided. Set GARMIN_MFA_CODE or GARMIN_MFA_CODE_FILE "
        "(optional: GARMIN_MFA_WAIT_SECONDS to poll)."
    )

# Get credentials from environment
email = os.environ.get("GARMIN_EMAIL")
password = os.environ.get("GARMIN_PASSWORD")
tokenstore = os.getenv("GARMINTOKENS") or "~/.garminconnect"
tokenstore_base64 = os.getenv("GARMINTOKENS_BASE64") or "~/.garminconnect_base64"


def init_api(email, password):
    """Initialize Garmin API with your credentials."""
    if os.environ.get("GARMIN_MCP_TEST_MODE") == "true":
        print("Running in TEST MODE with mock Garmin client.")
        from unittest.mock import MagicMock
        mock_client = MagicMock()
        mock_client.get_devices.return_value = [{"deviceId": "123", "modelName": "Fenix 7"}]
        mock_client.get_activities.return_value = [{"activityId": 12345, "activityName": "Morning Run", "startTimeLocal": "2026-06-05 08:00:00"}]
        mock_client.get_steps_data.return_value = [{"startDateTime": "2026-06-05T00:00:00", "steps": 10000}]
        return mock_client

    try:
        # Using Oauth1 and OAuth2 token files from directory
        print(
            f"Trying to login to Garmin Connect using token data from directory '{tokenstore}'...\n"
        )

        # Using Oauth1 and Oauth2 tokens from base64 encoded string
        # print(
        #     f"Trying to login to Garmin Connect using token data from file '{tokenstore_base64}'...\n"
        # )
        # dir_path = os.path.expanduser(tokenstore_base64)
        # with open(dir_path, "r") as token_file:
        #     tokenstore = token_file.read()

        garmin = Garmin()
        garmin.login(tokenstore)

    except (FileNotFoundError, GarthHTTPError, GarminConnectAuthenticationError):
        # Session is expired. You'll need to log in again
        print(
            "Login tokens not present, login with your Garmin Connect credentials to generate them.\n"
            f"They will be stored in '{tokenstore}' for future use.\n"
        )
        try:
            garmin = Garmin(
                email=email, password=password, is_cn=False, prompt_mfa=get_mfa
            )
            garmin.login()
            # Save Oauth1 and Oauth2 token files to directory for next login
            garmin.garth.dump(tokenstore)
            print(
                f"Oauth tokens stored in '{tokenstore}' directory for future use. (first method)\n"
            )
            # Encode Oauth1 and Oauth2 tokens to base64 string and safe to file for next login (alternative way)
            token_base64 = garmin.garth.dumps()
            dir_path = os.path.expanduser(tokenstore_base64)
            with open(dir_path, "w") as token_file:
                token_file.write(token_base64)
            print(
                f"Oauth tokens encoded as base64 string and saved to '{dir_path}' file for future use. (second method)\n"
            )
        except (
            FileNotFoundError,
            GarthHTTPError,
            GarminConnectAuthenticationError,
            requests.exceptions.HTTPError,
        ) as err:
            print(err)
            return None

    return garmin


import datetime
import hashlib
import time

# Global in-memory cache for short-term TTL
# format: cache_key -> (timestamp, value)
_mem_cache = {}
_MEM_CACHE_TTL = 300  # 5 minutes in seconds

def is_write_operation(func_name: str) -> bool:
    """Check if the tool function is a write/mutation operation."""
    return func_name.startswith(("add_", "set_", "update_", "delete_", "remove_", "post_", "create_"))

def is_date_older_than_7_days(date_str: str) -> bool:
    """Check if a date string in YYYY-MM-DD format is older than 7 days from today."""
    try:
        dt = datetime.datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
        today = datetime.date.today()
        return (today - dt).days > 7
    except Exception:
        # If it fails to parse (e.g. dynamic relative string like "today", "yesterday"),
        # treat it as recent (not older than 7 days) to prevent permanent caching of dynamic values.
        return False

def is_permanent_query(func_name: str, kwargs: dict) -> bool:
    """Determine if query results should be cached permanently on disk.
    
    1. If the tool is query-only and contains activity_id or activityId.
    2. If the tool contains date/start_date/end_date and all of them are older than 7 days.
    """
    if is_write_operation(func_name):
        return False
        
    # Activity IDs and device IDs: completed activities or device structures are generally historical/static
    if "activity_id" in kwargs or "activityId" in kwargs:
        return True
        
    has_date_args = False
    all_dates_old = True
    
    for key, val in kwargs.items():
        if key in ("date", "start_date", "end_date") and isinstance(val, str):
            has_date_args = True
            if not is_date_older_than_7_days(val):
                all_dates_old = False
                
    if has_date_args and all_dates_old:
        return True
        
    return False

def get_cache_key(func_name: str, args: tuple, kwargs: dict) -> str:
    """Generate a unique SHA256 key for a tool function call and its arguments."""
    # Serialize arguments reliably
    serialized = json.dumps({"args": args, "kwargs": kwargs}, sort_keys=True, default=str)
    args_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
    return f"{func_name}_{args_hash}"

from typing import Any, Optional

def read_from_disk_cache(cache_key: str) -> Optional[str]:
    """Read cached result from disk if it exists, otherwise return None."""
    try:
        cache_dir = os.path.join(os.path.expanduser(tokenstore), "cache", "perm")
        cache_file = os.path.join(cache_dir, f"{cache_key}.json")
        if os.path.exists(cache_file):
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"Error reading disk cache: {e}")
    return None

def write_to_disk_cache(cache_key: str, data: Any):
    """Write result to disk cache."""
    try:
        cache_dir = os.path.join(os.path.expanduser(tokenstore), "cache", "perm")
        os.makedirs(cache_dir, exist_ok=True)
        cache_file = os.path.join(cache_dir, f"{cache_key}.json")
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
    except Exception as e:
        print(f"Error writing disk cache: {e}")


def main():
    """Initialize the MCP server and register all tools"""

    import sys
    original_stdout = sys.stdout
    transport = os.environ.get("GARMIN_MCP_TRANSPORT", "http")
    if transport == "stdio":
        sys.stdout = sys.stderr

    # Initialize Garmin client
    garmin_client = init_api(email, password)
    if not garmin_client:
        print("Failed to initialize Garmin Connect client. Exiting.")
        return

    print("Garmin Connect client initialized successfully.")

    # Configure all modules with the Garmin client
    activity_management.configure(garmin_client)
    health_wellness.configure(garmin_client)
    user_profile.configure(garmin_client)
    devices.configure(garmin_client)
    gear_management.configure(garmin_client)
    weight_management.configure(garmin_client)
    challenges.configure(garmin_client)
    training.configure(garmin_client)
    workouts.configure(garmin_client)
    data_management.configure(garmin_client)
    womens_health.configure(garmin_client)
    recommendations.configure(garmin_client)

    # Create the MCP app
    app = FastMCP("Garmin Connect v1.0")

    # Patch app.tool to support hybrid caching and thread-concurrency
    original_tool = app.tool

    def patched_tool(*args, **kwargs):
        decorator = original_tool(*args, **kwargs)

        def wrapper(func):
            import inspect
            from functools import wraps
            import asyncio

            @wraps(func)
            async def async_wrapper(*a, **kw):
                func_name = func.__name__

                # 1. Bypass cache for writes/mutations
                if is_write_operation(func_name):
                    print(f"[CACHE] Write operation '{func_name}' with args={a} kwargs={kw}. Bypassing cache.", file=sys.stderr, flush=True)
                    def run_write_sync():
                        if inspect.iscoroutinefunction(func):
                            coro = func(*a, **kw)
                            try:
                                coro.send(None)
                            except StopIteration as e:
                                return e.value
                        else:
                            return func(*a, **kw)
                    return await asyncio.to_thread(run_write_sync)

                # Generate cache key
                cache_key = get_cache_key(func_name, a, kw)

                # 2. Check Disk Cache (for historical/permanent data)
                if is_permanent_query(func_name, kw):
                    cached_val = read_from_disk_cache(cache_key)
                    if cached_val is not None:
                        print(f"[CACHE] Disk cache HIT for '{func_name}' with kwargs={kw} (key: {cache_key})", file=sys.stderr, flush=True)
                        return cached_val

                # 3. Check Memory Cache (for recent/dynamic data)
                else:
                    now = time.time()
                    if cache_key in _mem_cache:
                        ts, val = _mem_cache[cache_key]
                        if now - ts < _MEM_CACHE_TTL:
                            print(f"[CACHE] Memory cache HIT for '{func_name}' with kwargs={kw} (key: {cache_key})", file=sys.stderr, flush=True)
                            return val

                # 4. Cache Miss: Execute tool in thread executor
                print(f"[CACHE] Cache MISS for '{func_name}' with kwargs={kw} (key: {cache_key}). Querying Garmin API in background thread...", file=sys.stderr, flush=True)
                def run_tool_sync():
                    if inspect.iscoroutinefunction(func):
                        coro = func(*a, **kw)
                        try:
                            coro.send(None)
                        except StopIteration as e:
                            return e.value
                    else:
                        return func(*a, **kw)

                result = await asyncio.to_thread(run_tool_sync)

                # 5. Store result in appropriate cache
                if is_permanent_query(func_name, kw):
                    print(f"[CACHE] Storing result for '{func_name}' in permanent disk cache (key: {cache_key}).", file=sys.stderr, flush=True)
                    write_to_disk_cache(cache_key, result)
                else:
                    print(f"[CACHE] Storing result for '{func_name}' in memory cache (key: {cache_key}).", file=sys.stderr, flush=True)
                    _mem_cache[cache_key] = (time.time(), result)

                return result

            return decorator(async_wrapper)

        return wrapper

    app.tool = patched_tool

    # Register tools from all modules
    app = activity_management.register_tools(app)
    app = health_wellness.register_tools(app)
    app = user_profile.register_tools(app)
    app = devices.register_tools(app)
    app = gear_management.register_tools(app)
    app = weight_management.register_tools(app)
    app = challenges.register_tools(app)
    app = training.register_tools(app)
    app = workouts.register_tools(app)
    app = data_management.register_tools(app)
    app = womens_health.register_tools(app)
    app = recommendations.register_tools(app)

    # Add simple HTTP health and root routes if the underlying ASGI app exposes FastAPI-style router
    try:
        asgi = getattr(app, "app", None) or getattr(app, "asgi", None) or getattr(app, "asgi_app", None) or getattr(app, "_app", None)
        if asgi is not None and hasattr(asgi, "add_api_route"):
            from typing import Any
            def _ok() -> Any:
                return {"status": "ok", "service": "garmin-mcp"}
            # Health endpoints commonly used by k8s/istio
            asgi.add_api_route("/healthz", _ok, methods=["GET"])  # type: ignore[attr-defined]
            asgi.add_api_route("/readyz", _ok, methods=["GET"])  # type: ignore[attr-defined]
            # Friendly root so GET / doesn't 404
            asgi.add_api_route("/", _ok, methods=["GET"])  # type: ignore[attr-defined]
    except Exception:
        pass

    # Add activity listing tool directly to the app
    @app.tool()
    async def list_activities(limit: int = 5) -> str:
        """List recent Garmin activities"""
        try:
            activities = garmin_client.get_activities(0, limit)

            if not activities:
                return "No activities found."

            return _to_json_str(activities)
        except Exception as e:
            return f"Error retrieving activities: {str(e)}"

    # Run the MCP server (Streamable HTTP by default for Kubernetes)
    transport = os.environ.get("GARMIN_MCP_TRANSPORT", "http")
    host = os.environ.get("GARMIN_MCP_HOST", "0.0.0.0")
    port_str = os.environ.get("GARMIN_MCP_PORT", "8000")
    path = os.environ.get("GARMIN_MCP_PATH", "/")
    try:
        port = int(port_str)
    except ValueError:
        port = 8000

    if transport == "stdio":
        sys.stdout = original_stdout
        app.run()
    else:
        print(f"Starting MCP with transport={transport}, host={host}, port={port}, path={path}")
        # Provide simple health and authorization checks by wrapping the ASGI app when possible
        class _AuthAndHealthWrapper:
            def __init__(self, inner):
                self.inner = inner

            async def __call__(self, scope, receive, send):
                if scope.get("type") == "http":
                    path_value = scope.get("path", "")
                    method = scope.get("method", "")
                    
                    # 1. Handle public health routes
                    if method == "GET" and path_value in ("/", "/healthz", "/readyz"):
                        body = b'{"status":"ok","service":"garmin-mcp"}'
                        await send({
                            "type": "http.response.start",
                            "status": 200,
                            "headers": [(b"content-type", b"application/json")],
                        })
                        await send({"type": "http.response.body", "body": body})
                        return
                    
                    # 2. Check simple API key auth if GARMIN_MCP_API_KEY is configured
                    api_key = os.environ.get("GARMIN_MCP_API_KEY")
                    if api_key:
                        headers = dict(scope.get("headers", []))
                        auth_header = headers.get(b"authorization", b"").decode("utf-8")
                        api_key_header = headers.get(b"x-api-key", b"").decode("utf-8")
                        
                        # Parse query string for ?api_key=...
                        query_string = scope.get("query_string", b"").decode("utf-8")
                        import urllib.parse
                        query_params = urllib.parse.parse_qs(query_string)
                        api_key_query = query_params.get("api_key", [None])[0]
                        
                        authorized = False
                        if auth_header == f"Bearer {api_key}":
                            authorized = True
                        elif api_key_header == api_key:
                            authorized = True
                        elif api_key_query == api_key:
                            authorized = True
                            
                        if not authorized:
                            body = b'{"error":"Unauthorized"}'
                            await send({
                                "type": "http.response.start",
                                "status": 401,
                                "headers": [(b"content-type", b"application/json")],
                            })
                            await send({"type": "http.response.body", "body": body})
                            return
                            
                return await self.inner(scope, receive, send)

        # Aggressively monkey-patch uvicorn at multiple levels to force 0.0.0.0 binding
        if host == "0.0.0.0":
            try:
                import uvicorn  # type: ignore
                import uvicorn.config  # type: ignore
                import uvicorn.server  # type: ignore
                
                # Patch uvicorn.run
                original_run = uvicorn.run
                def patched_run(app, *args, **kwargs):
                    if "host" not in kwargs or kwargs.get("host") == "127.0.0.1":
                        kwargs["host"] = "0.0.0.0"
                    if "port" not in kwargs and port:
                        kwargs["port"] = port
                    return original_run(app, *args, **kwargs)
                uvicorn.run = patched_run
                
                # Patch Config.__init__ to force host
                original_config_init = uvicorn.config.Config.__init__
                def patched_config_init(self, *args, **kwargs):
                    if "host" not in kwargs or kwargs.get("host") == "127.0.0.1" or kwargs.get("host") is None:
                        kwargs["host"] = "0.0.0.0"
                    if "port" not in kwargs and port:
                        kwargs["port"] = port
                    return original_config_init(self, *args, **kwargs)
                uvicorn.config.Config.__init__ = patched_config_init
                
                # Patch Server.__init__ to force host
                original_server_init = uvicorn.server.Server.__init__
                def patched_server_init(self, config, *args, **kwargs):
                    if hasattr(config, 'host') and (config.host == "127.0.0.1" or config.host is None):
                        config.host = "0.0.0.0"
                    if hasattr(config, 'port') and not config.port and port:
                        config.port = port
                    return original_server_init(self, config, *args, **kwargs)
                uvicorn.server.Server.__init__ = patched_server_init
                
                print("Patched uvicorn at multiple levels to force 0.0.0.0 binding")
            except Exception as e:
                print(f"Warning: Could not patch uvicorn: {e}")

        # Try to locate the underlying ASGI app and run it directly (wrapped) so health endpoints work
        try:
            import uvicorn  # type: ignore
            underlying = None
            if transport == "streamable-http" and hasattr(app, "streamable_http_app"):
                underlying = app.streamable_http_app()
            elif transport == "sse" and hasattr(app, "sse_app"):
                underlying = app.sse_app()

            if underlying is None:
                underlying = getattr(app, "app", None) or getattr(app, "asgi", None) or getattr(app, "asgi_app", None) or getattr(app, "_app", None)
                if underlying is None:
                    for factory_name in ("build_asgi", "create_asgi", "make_asgi_app"):
                        factory = getattr(app, factory_name, None)
                        if callable(factory):
                            underlying = factory()
                            break
            if underlying is not None:
                wrapped = _AuthAndHealthWrapper(underlying)
                uvicorn.run(wrapped, host=host, port=port)
                return
        except Exception:
            pass
        # Try to run with explicit parameters first
        try:
            app.run(transport=transport, host=host, port=port, path=path)
            return
        except TypeError:
            pass
        try:
            app.run(transport=transport, hostname=host, port=port, path=path)
            return
        except TypeError:
            pass
        try:
            app.run(transport=transport, address=host, port=port, path=path)
            return
        except TypeError:
            pass
        # Final fallback - the monkey-patch should catch this
        app.run(transport=transport)


if __name__ == "__main__":
    main()
