import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch
import threading
import requests
import tempfile
import datetime

# Add the src directory to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

class TestAuthAndCache(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Set up a temporary directory for cache testing
        cls.temp_dir = tempfile.TemporaryDirectory()
        os.environ["GARMINTOKENS"] = cls.temp_dir.name

        # Set up environment variables
        os.environ["GARMIN_MCP_TRANSPORT"] = "sse"
        os.environ["GARMIN_MCP_PORT"] = "8001"
        os.environ["GARMIN_MCP_API_KEY"] = "my-test-api-key"
        os.environ["GARMIN_EMAIL"] = "test@example.com"
        os.environ["GARMIN_PASSWORD"] = "password"

        # Mock the Garmin Connect client
        cls.mock_garmin = MagicMock()
        cls.mock_garmin.get_devices.return_value = [{"deviceId": "123", "modelName": "Fenix 7"}]
        cls.mock_garmin.get_activities.return_value = [{"activityId": 12345, "activityName": "Morning Run"}]
        cls.mock_garmin.get_sleep_data.return_value = {"dailySleepDTO": {"sleepScoreTotal": 85}}

        # Patch init_api to return our mock
        cls.init_api_patcher = patch("garmin_mcp.init_api", return_value=cls.mock_garmin)
        cls.init_api_patcher.start()

        # Import main and start server in a background thread
        from garmin_mcp import main
        cls.server_thread = threading.Thread(target=main, daemon=True)
        cls.server_thread.start()
        
        # Wait for server to start
        time.sleep(2)

    @classmethod
    def tearDownClass(cls):
        cls.init_api_patcher.stop()
        cls.temp_dir.cleanup()

    def test_healthz_unauthenticated(self):
        # Health endpoints should be accessible without credentials
        r = requests.get("http://localhost:8001/healthz")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"status": "ok", "service": "garmin-mcp"})

    def test_mcp_unauthenticated(self):
        # Accessing protected endpoints without API key should return 401
        r = requests.get("http://localhost:8001/sse")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json(), {"error": "Unauthorized"})

    def test_mcp_authenticated_bearer(self):
        # Accessing protected endpoints with correct Bearer token should succeed
        headers = {"Authorization": "Bearer my-test-api-key"}
        r = requests.get("http://localhost:8001/sse", headers=headers, stream=True)
        self.assertEqual(r.status_code, 200)

    def test_mcp_authenticated_query_param(self):
        # Accessing protected endpoints with correct query param should succeed
        r = requests.get("http://localhost:8001/sse?api_key=my-test-api-key", stream=True)
        self.assertEqual(r.status_code, 200)

    def test_date_older_than_7_days(self):
        from garmin_mcp import is_date_older_than_7_days
        # Helper to generate old/recent dates
        today = datetime.date.today()
        old_date = (today - datetime.timedelta(days=10)).strftime("%Y-%m-%d")
        recent_date = (today - datetime.timedelta(days=2)).strftime("%Y-%m-%d")

        self.assertTrue(is_date_older_than_7_days(old_date))
        self.assertFalse(is_date_older_than_7_days(recent_date))
        self.assertFalse(is_date_older_than_7_days("invalid-date"))
        self.assertFalse(is_date_older_than_7_days("today"))

    def test_is_permanent_query(self):
        from garmin_mcp import is_permanent_query
        # Activity ID queries should be permanent
        self.assertTrue(is_permanent_query("get_activity", {"activity_id": 12345}))
        self.assertTrue(is_permanent_query("get_activity", {"activityId": 12345}))

        # Queries with date older than 7 days should be permanent
        today = datetime.date.today()
        old_date_str = (today - datetime.timedelta(days=10)).strftime("%Y-%m-%d")
        recent_date_str = (today - datetime.timedelta(days=2)).strftime("%Y-%m-%d")

        self.assertTrue(is_permanent_query("get_steps_data", {"date": old_date_str}))
        self.assertFalse(is_permanent_query("get_steps_data", {"date": recent_date_str}))

        # Write operations should never be cached permanently
        self.assertFalse(is_permanent_query("add_activity", {"activity_id": 12345}))

    def test_get_cache_key(self):
        from garmin_mcp import get_cache_key
        key1 = get_cache_key("test_func", (1, 2), {"a": "b"})
        key2 = get_cache_key("test_func", (1, 2), {"a": "b"})
        key3 = get_cache_key("test_func", (1, 3), {"a": "b"})

        self.assertEqual(key1, key2)
        self.assertNotEqual(key1, key3)

    def test_disk_cache_read_write(self):
        from garmin_mcp import write_to_disk_cache, read_from_disk_cache
        test_key = "test_cache_key"
        test_data = {"hello": "world", "nested": [1, 2, 3]}

        write_to_disk_cache(test_key, test_data)
        cached = read_from_disk_cache(test_key)
        self.assertEqual(cached, test_data)

        # Check non-existent key
        self.assertIsNone(read_from_disk_cache("non_existent_key"))

if __name__ == "__main__":
    unittest.main()