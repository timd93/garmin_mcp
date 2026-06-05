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

        # Verify max_age_seconds checks
        cached_valid = read_from_disk_cache(test_key, max_age_seconds=10)
        self.assertEqual(cached_valid, test_data)

        # Verify expired caches return None
        cached_expired = read_from_disk_cache(test_key, max_age_seconds=-1)
        self.assertIsNone(cached_expired)

        # Check non-existent key
        self.assertIsNone(read_from_disk_cache("non_existent_key"))

    def test_prefetch_daemon(self):
        import asyncio
        from garmin_mcp import prefetch_background_daemon, get_cache_key, read_from_disk_cache
        
        # Configure prefetch range to 1 day for testing speed
        os.environ["GARMIN_PREFETCH_DAYS"] = "1"
        
        # Setup mock client
        mock_client = MagicMock()
        mock_client.get_activities_by_date.return_value = [{"activityId": 99999}]
        mock_client.get_stats.return_value = {"calories": 2000}
        mock_client.get_sleep_data.return_value = {"sleepScore": 90}
        mock_client.get_steps_data.return_value = {"steps": 8000}
        mock_client.get_hrv_data.return_value = {"hrv": 55}
        mock_client.get_training_readiness.return_value = {"readiness": 85}
        mock_client.get_activity.return_value = {"name": "Test Run"}
        mock_client.get_activity_splits.return_value = {"splits": []}
        
        async def mock_sleep(delay):
            if delay == 12 * 3600:
                raise KeyboardInterrupt("Cycle complete")
            return
            
        # Run prefetch daemon using asyncio event loop (First run - populates cache)
        with patch("asyncio.sleep", side_effect=mock_sleep):
            try:
                asyncio.run(prefetch_background_daemon(mock_client))
            except KeyboardInterrupt:
                pass # Expected interruption at the end of the first cycle
                
        # Reset mock client to clear call history
        mock_client.reset_mock()
        
        # Run prefetch daemon a second time (Should hit cache for everything)
        with patch("asyncio.sleep", side_effect=mock_sleep):
            try:
                asyncio.run(prefetch_background_daemon(mock_client))
            except KeyboardInterrupt:
                pass
                
        # Verify mock client was NOT called on the second run (100% cache hits!)
        mock_client.get_stats.assert_not_called()
        mock_client.get_sleep_data.assert_not_called()
        mock_client.get_steps_data.assert_not_called()
        mock_client.get_hrv_data.assert_not_called()
        mock_client.get_training_readiness.assert_not_called()
        mock_client.get_activity.assert_not_called()

        # Verify that expected keys were written to disk cache
        today = datetime.date.today()
        today_str = today.strftime("%Y-%m-%d")
        yesterday_str = (today - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        
        # 1. Activities list cache key
        act_list_key = get_cache_key("get_activities_by_date", (), {"start_date": yesterday_str, "end_date": today_str, "activity_type": ""})
        self.assertIsNotNone(read_from_disk_cache(act_list_key))
        
        # 2. Daily stats cache key for today
        stats_key = get_cache_key("get_stats", (), {"date": today_str})
        self.assertIsNotNone(read_from_disk_cache(stats_key))
        
        # 3. Activity details cache key
        act_detail_key = get_cache_key("get_activity", (), {"activity_id": 99999})
        self.assertIsNotNone(read_from_disk_cache(act_detail_key))

if __name__ == "__main__":
    unittest.main()