import asyncio
from unittest.async_case import IsolatedAsyncioTestCase
from core.rate_limiter.memory import InMemoryRateLimiter


class TestInMemoryRateLimiter(IsolatedAsyncioTestCase):
    def setUp(self):
        self.limiter = InMemoryRateLimiter()

    async def test_basic_rate_limiting(self):
        key = "test_user"
        limit = 5
        window = 60

        # Should allow first 5 requests
        for i in range(limit):
            is_allowed, retry_after = await self.limiter.is_allowed(key, limit, window)
            self.assertTrue(is_allowed, f"Request {i + 1} should be allowed")
            self.assertIsNone(retry_after)

        # 6th request should be blocked
        is_allowed, retry_after = await self.limiter.is_allowed(key, limit, window)
        self.assertFalse(is_allowed, "Request beyond limit should be blocked")
        self.assertIsNotNone(retry_after)
        self.assertGreater(retry_after, 0)

    async def test_sliding_window(self):
        key = "sliding_test"
        limit = 3
        window = 2

        for _ in range(limit):
            is_allowed, _ = await self.limiter.is_allowed(key, limit, window)
            self.assertTrue(is_allowed)

        is_allowed, retry_after = await self.limiter.is_allowed(key, limit, window)
        self.assertFalse(is_allowed)

        await asyncio.sleep(window + 0.1)
        is_allowed, retry_after = await self.limiter.is_allowed(key, limit, window)
        self.assertTrue(is_allowed, "Should allow requests after window expires")
        self.assertIsNone(retry_after)

    async def test_different_keys_independent(self):
        limit = 3
        window = 60

        for _ in range(limit):
            is_allowed, _ = await self.limiter.is_allowed("key1", limit, window)
            self.assertTrue(is_allowed)

        is_allowed, _ = await self.limiter.is_allowed("key1", limit, window)
        self.assertFalse(is_allowed)

        is_allowed, _ = await self.limiter.is_allowed("key2", limit, window)
        self.assertTrue(is_allowed, "Different keys should have independent limits")

    async def test_get_remaining(self):
        key = "remaining_test"
        limit = 5
        window = 60

        remaining = await self.limiter.get_remaining(key, limit)
        self.assertEqual(remaining, limit)

        await self.limiter.is_allowed(key, limit, window)
        await self.limiter.is_allowed(key, limit, window)
        remaining = await self.limiter.get_remaining(key, limit)
        self.assertEqual(remaining, 3)

        for _ in range(3):
            await self.limiter.is_allowed(key, limit, window)
        remaining = await self.limiter.get_remaining(key, limit)
        self.assertEqual(remaining, 0)

    async def test_reset(self):
        key = "reset_test"
        limit = 3
        window = 60

        for _ in range(limit):
            await self.limiter.is_allowed(key, limit, window)

        is_allowed, _ = await self.limiter.is_allowed(key, limit, window)
        self.assertFalse(is_allowed)

        await self.limiter.reset(key)
        is_allowed, _ = await self.limiter.is_allowed(key, limit, window)
        self.assertTrue(is_allowed, "Should allow requests after reset")

        remaining = await self.limiter.get_remaining(key, limit)
        self.assertEqual(remaining, limit - 1)

    async def test_cleanup_expired(self):
        key1 = "cleanup_key1"
        key2 = "cleanup_key2"
        limit = 3
        window = 1

        await self.limiter.is_allowed(key1, limit, window)
        await self.limiter.is_allowed(key2, limit, window)

        await asyncio.sleep(window + 0.1)
        await self.limiter.cleanup_expired(window)

        remaining1 = await self.limiter.get_remaining(key1, limit)
        remaining2 = await self.limiter.get_remaining(key2, limit)
        self.assertEqual(remaining1, limit)
        self.assertEqual(remaining2, limit)

    async def test_max_keys_evicts_oldest_key(self):
        limiter = InMemoryRateLimiter(max_keys=2)

        await limiter.is_allowed("key1", 1, 60)
        await limiter.is_allowed("key2", 1, 60)
        await limiter.is_allowed("key3", 1, 60)

        self.assertEqual(await limiter.get_remaining("key1", 1), 1)
        self.assertEqual(await limiter.get_remaining("key2", 1), 0)
        self.assertEqual(await limiter.get_remaining("key3", 1), 0)

    async def test_retry_after_calculation(self):
        key = "retry_test"
        limit = 2
        window = 10

        await self.limiter.is_allowed(key, limit, window)
        await self.limiter.is_allowed(key, limit, window)

        is_allowed, retry_after = await self.limiter.is_allowed(key, limit, window)
        self.assertFalse(is_allowed)
        self.assertGreater(retry_after, 0)
        self.assertLessEqual(retry_after, window)
        self.assertGreater(retry_after, window - 1)

    async def test_concurrent_requests(self):
        key = "concurrent_test"
        limit = 10
        window = 60

        tasks = [self.limiter.is_allowed(key, limit, window) for _ in range(20)]
        results = await asyncio.gather(*tasks)

        allowed_count = sum(1 for is_allowed, _ in results if is_allowed)
        self.assertEqual(allowed_count, limit)
        blocked_count = sum(1 for is_allowed, _ in results if not is_allowed)
        self.assertEqual(blocked_count, 10)

    async def test_zero_limit(self):
        key = "zero_limit_test"
        is_allowed, retry_after = await self.limiter.is_allowed(key, 0, 60)
        self.assertFalse(is_allowed)
        self.assertIsNotNone(retry_after)

    async def test_large_limit(self):
        key = "large_limit_test"
        limit = 1000

        for i in range(limit):
            is_allowed, _ = await self.limiter.is_allowed(key, limit, 60)
            self.assertTrue(is_allowed, f"Request {i + 1} should be allowed")

        is_allowed, _ = await self.limiter.is_allowed(key, limit, 60)
        self.assertFalse(is_allowed)
