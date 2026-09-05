#!/usr/bin/env python3
"""
Database performance benchmark script.

This script tests database performance against the target of 100 signals/second
write rate and provides comprehensive performance metrics.
"""

import asyncio
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Tuple
import statistics

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.database import initialize_database, close_database
from src.database.repository import RepositoryFactory
from src.database.models import ParsedAction, ParserType, SignalStatus, PositionStatus

logger = logging.getLogger(__name__)


class DatabaseBenchmark:
    """Database performance benchmark."""
    
    def __init__(self, database_url: str = None):
        """
        Initialize benchmark.
        
        Args:
            database_url: Database URL override
        """
        self.database_url = database_url
        self.results = {}
    
    async def setup(self):
        """Setup benchmark environment."""
        await initialize_database(self.database_url, run_migrations=True)
        self.repo_factory = RepositoryFactory(database_url=self.database_url)
    
    async def teardown(self):
        """Cleanup benchmark environment."""
        await close_database()
    
    def generate_signal_data(self, count: int) -> List[dict]:
        """
        Generate signal test data.
        
        Args:
            count: Number of signals to generate
            
        Returns:
            List of signal data dictionaries
        """
        signals = []
        base_time = datetime.utcnow()
        
        for i in range(count):
            signals.append({
                'telegram_message_id': 10000 + i,
                'telegram_chat_id': -100123456789,
                'sender': f'test_user_{i % 10}',
                'timestamp': base_time,
                'raw_text': f'BUY GOLD at {2000 + i} SL {1995 + i} TP {2010 + i}',
                'parsed_action': ParsedAction.BUY if i % 2 == 0 else ParsedAction.SELL,
                'symbol': ['GOLD', 'EURUSD', 'GBPUSD'][i % 3],
                'entry_price': 2000.0 + i,
                'stop_loss': 1995.0 + i,
                'take_profit': 2010.0 + i,
                'confidence_score': 0.8 + (i % 20) * 0.01,
                'parser_type': ParserType.REGEX,
                'status': SignalStatus.PENDING
            })
        
        return signals
    
    def generate_position_data(self, signal_ids: List[int]) -> List[dict]:
        """
        Generate position test data.
        
        Args:
            signal_ids: List of signal IDs to create positions for
            
        Returns:
            List of position data dictionaries
        """
        positions = []
        base_time = datetime.utcnow()
        
        for i, signal_id in enumerate(signal_ids):
            positions.append({
                'signal_id': signal_id,
                'mt5_ticket': 100000 + i,
                'open_time': base_time,
                'open_price': 2000.0 + i,
                'volume': 0.1,
                'current_sl': 1995.0 + i,
                'current_tp': 2010.0 + i,
                'profit': (i % 100) - 50,  # Mix of profitable and losing positions
                'status': PositionStatus.OPEN
            })
        
        return positions
    
    async def benchmark_signal_writes(self, count: int) -> Tuple[float, float]:
        """
        Benchmark signal write performance.
        
        Args:
            count: Number of signals to write
            
        Returns:
            Tuple of (total_time, writes_per_second)
        """
        signals = self.generate_signal_data(count)
        signal_repo = self.repo_factory.get_signal_repository()
        
        start_time = time.time()
        
        # Batch create signals
        tasks = []
        for signal_data in signals:
            tasks.append(signal_repo.create(**signal_data))
        
        await asyncio.gather(*tasks)
        
        end_time = time.time()
        total_time = end_time - start_time
        writes_per_second = count / total_time
        
        logger.info(f"Signal writes: {count} signals in {total_time:.2f}s ({writes_per_second:.2f} signals/s)")
        
        return total_time, writes_per_second
    
    async def benchmark_signal_reads(self, count: int) -> Tuple[float, float]:
        """
        Benchmark signal read performance.
        
        Args:
            count: Number of read operations
            
        Returns:
            Tuple of (total_time, reads_per_second)
        """
        signal_repo = self.repo_factory.get_signal_repository()
        
        # First create some signals to read
        signals = self.generate_signal_data(min(count, 1000))
        for signal_data in signals:
            await signal_repo.create(**signal_data)
        
        start_time = time.time()
        
        # Perform read operations
        tasks = []
        for i in range(count):
            message_id = 10000 + (i % len(signals))
            tasks.append(signal_repo.find_by_message_id(message_id))
        
        await asyncio.gather(*tasks)
        
        end_time = time.time()
        total_time = end_time - start_time
        reads_per_second = count / total_time
        
        logger.info(f"Signal reads: {count} reads in {total_time:.2f}s ({reads_per_second:.2f} reads/s)")
        
        return total_time, reads_per_second
    
    async def benchmark_complex_queries(self, count: int) -> Tuple[float, float]:
        """
        Benchmark complex query performance.
        
        Args:
            count: Number of query operations
            
        Returns:
            Tuple of (total_time, queries_per_second)
        """
        signal_repo = self.repo_factory.get_signal_repository()
        
        start_time = time.time()
        
        # Perform complex queries
        tasks = []
        for i in range(count):
            if i % 3 == 0:
                tasks.append(signal_repo.get_recent_signals(minutes=60))
            elif i % 3 == 1:
                symbol = ['GOLD', 'EURUSD', 'GBPUSD'][i % 3]
                tasks.append(signal_repo.get_signals_by_symbol(symbol, limit=50))
            else:
                tasks.append(signal_repo.get_signals_with_positions())
        
        await asyncio.gather(*tasks)
        
        end_time = time.time()
        total_time = end_time - start_time
        queries_per_second = count / total_time
        
        logger.info(f"Complex queries: {count} queries in {total_time:.2f}s ({queries_per_second:.2f} queries/s)")
        
        return total_time, queries_per_second
    
    async def benchmark_concurrent_operations(self, concurrent_users: int = 10, 
                                            operations_per_user: int = 100) -> dict:
        """
        Benchmark concurrent database operations.
        
        Args:
            concurrent_users: Number of concurrent user simulations
            operations_per_user: Operations per user
            
        Returns:
            Dictionary with concurrent operation metrics
        """
        async def user_operations(user_id: int):
            """Simulate one user's database operations."""
            signal_repo = self.repo_factory.get_signal_repository()
            position_repo = self.repo_factory.get_position_repository()
            
            times = []
            
            for i in range(operations_per_user):
                start = time.time()
                
                # Mix of read and write operations
                if i % 4 == 0:
                    # Write signal
                    signal_data = {
                        'telegram_message_id': user_id * 10000 + i,
                        'telegram_chat_id': -100123456789,
                        'sender': f'user_{user_id}',
                        'timestamp': datetime.utcnow(),
                        'raw_text': f'Test signal {i}',
                        'parsed_action': ParsedAction.BUY,
                        'symbol': 'GOLD',
                        'parser_type': ParserType.REGEX
                    }
                    await signal_repo.create(**signal_data)
                
                elif i % 4 == 1:
                    # Read recent signals
                    await signal_repo.get_recent_signals(minutes=30)
                
                elif i % 4 == 2:
                    # Read signals by symbol
                    await signal_repo.get_signals_by_symbol('GOLD', limit=20)
                
                else:
                    # Read open positions
                    await position_repo.get_open_positions()
                
                times.append(time.time() - start)
            
            return times
        
        start_time = time.time()
        
        # Run concurrent user operations
        tasks = []
        for user_id in range(concurrent_users):
            tasks.append(user_operations(user_id))
        
        user_times = await asyncio.gather(*tasks)
        
        end_time = time.time()
        total_time = end_time - start_time
        
        # Collect metrics
        all_times = [time for user_time in user_times for time in user_time]
        total_operations = concurrent_users * operations_per_user
        
        metrics = {
            'total_time': total_time,
            'total_operations': total_operations,
            'operations_per_second': total_operations / total_time,
            'concurrent_users': concurrent_users,
            'avg_operation_time': statistics.mean(all_times),
            'median_operation_time': statistics.median(all_times),
            'p95_operation_time': sorted(all_times)[int(len(all_times) * 0.95)],
            'p99_operation_time': sorted(all_times)[int(len(all_times) * 0.99)],
            'max_operation_time': max(all_times),
            'min_operation_time': min(all_times)
        }
        
        logger.info(f"Concurrent operations: {total_operations} ops in {total_time:.2f}s "
                   f"({metrics['operations_per_second']:.2f} ops/s)")
        logger.info(f"Average operation time: {metrics['avg_operation_time']*1000:.2f}ms")
        logger.info(f"P95 operation time: {metrics['p95_operation_time']*1000:.2f}ms")
        logger.info(f"P99 operation time: {metrics['p99_operation_time']*1000:.2f}ms")
        
        return metrics
    
    async def benchmark_sustained_load(self, duration_seconds: int = 60, 
                                     target_rate: int = 50) -> dict:
        """
        Benchmark sustained database load.
        
        Args:
            duration_seconds: Test duration in seconds
            target_rate: Target operations per second
            
        Returns:
            Dictionary with sustained load metrics
        """
        signal_repo = self.repo_factory.get_signal_repository()
        
        start_time = time.time()
        end_time = start_time + duration_seconds
        
        operations_completed = 0
        operation_times = []
        intervals = []
        
        message_id_counter = 50000
        
        while time.time() < end_time:
            interval_start = time.time()
            
            # Perform batch of operations to meet target rate
            batch_size = max(1, target_rate // 10)  # 10 batches per second
            
            tasks = []
            for _ in range(batch_size):
                signal_data = {
                    'telegram_message_id': message_id_counter,
                    'telegram_chat_id': -100123456789,
                    'sender': 'load_test_user',
                    'timestamp': datetime.utcnow(),
                    'raw_text': f'Load test signal {message_id_counter}',
                    'parsed_action': ParsedAction.BUY,
                    'symbol': 'GOLD',
                    'parser_type': ParserType.REGEX
                }
                tasks.append(signal_repo.create(**signal_data))
                message_id_counter += 1
            
            batch_start = time.time()
            await asyncio.gather(*tasks)
            batch_time = time.time() - batch_start
            
            operations_completed += len(tasks)
            operation_times.extend([batch_time / len(tasks)] * len(tasks))
            
            # Wait to maintain target rate
            interval_time = time.time() - interval_start
            intervals.append(interval_time)
            
            target_interval = 1.0 / (target_rate / batch_size)
            if interval_time < target_interval:
                await asyncio.sleep(target_interval - interval_time)
        
        actual_duration = time.time() - start_time
        actual_rate = operations_completed / actual_duration
        
        metrics = {
            'target_duration': duration_seconds,
            'actual_duration': actual_duration,
            'target_rate': target_rate,
            'actual_rate': actual_rate,
            'operations_completed': operations_completed,
            'avg_operation_time': statistics.mean(operation_times),
            'p95_operation_time': sorted(operation_times)[int(len(operation_times) * 0.95)],
            'max_operation_time': max(operation_times),
            'rate_accuracy': (actual_rate / target_rate) * 100
        }
        
        logger.info(f"Sustained load: {operations_completed} ops in {actual_duration:.2f}s "
                   f"({actual_rate:.2f} ops/s, target: {target_rate} ops/s)")
        logger.info(f"Rate accuracy: {metrics['rate_accuracy']:.1f}%")
        
        return metrics
    
    async def run_full_benchmark(self) -> dict:
        """
        Run complete database benchmark suite.
        
        Returns:
            Dictionary with all benchmark results
        """
        logger.info("Starting database performance benchmark...")
        
        await self.setup()
        
        try:
            # Test 1: Signal write performance (target: 100 signals/second)
            logger.info("\n=== Signal Write Performance ===")
            write_time, write_rate = await self.benchmark_signal_writes(1000)
            self.results['signal_writes'] = {
                'count': 1000,
                'time': write_time,
                'rate': write_rate,
                'target_met': write_rate >= 100
            }
            
            # Test 2: Signal read performance
            logger.info("\n=== Signal Read Performance ===")
            read_time, read_rate = await self.benchmark_signal_reads(5000)
            self.results['signal_reads'] = {
                'count': 5000,
                'time': read_time,
                'rate': read_rate
            }
            
            # Test 3: Complex query performance
            logger.info("\n=== Complex Query Performance ===")
            query_time, query_rate = await self.benchmark_complex_queries(500)
            self.results['complex_queries'] = {
                'count': 500,
                'time': query_time,
                'rate': query_rate
            }
            
            # Test 4: Concurrent operations
            logger.info("\n=== Concurrent Operations ===")
            concurrent_metrics = await self.benchmark_concurrent_operations(
                concurrent_users=5, 
                operations_per_user=200
            )
            self.results['concurrent_operations'] = concurrent_metrics
            
            # Test 5: Sustained load (target: 50 messages/minute for 1 hour simulation)
            logger.info("\n=== Sustained Load Test ===")
            sustained_metrics = await self.benchmark_sustained_load(
                duration_seconds=60,  # 1 minute for testing
                target_rate=50  # 50 per second to simulate burst
            )
            self.results['sustained_load'] = sustained_metrics
            
        finally:
            await self.teardown()
        
        return self.results
    
    def print_summary(self):
        """Print benchmark results summary."""
        logger.info("\n" + "="*50)
        logger.info("DATABASE PERFORMANCE BENCHMARK SUMMARY")
        logger.info("="*50)
        
        # Signal writes
        writes = self.results.get('signal_writes', {})
        if writes:
            status = "✅ PASS" if writes.get('target_met', False) else "❌ FAIL"
            logger.info(f"Signal Writes: {writes['rate']:.1f} signals/s {status}")
            logger.info(f"  Target: 100 signals/s")
        
        # Signal reads
        reads = self.results.get('signal_reads', {})
        if reads:
            logger.info(f"Signal Reads: {reads['rate']:.1f} reads/s")
        
        # Complex queries
        queries = self.results.get('complex_queries', {})
        if queries:
            logger.info(f"Complex Queries: {queries['rate']:.1f} queries/s")
        
        # Concurrent operations
        concurrent = self.results.get('concurrent_operations', {})
        if concurrent:
            logger.info(f"Concurrent Ops: {concurrent['operations_per_second']:.1f} ops/s")
            logger.info(f"  P95 latency: {concurrent['p95_operation_time']*1000:.2f}ms")
        
        # Sustained load
        sustained = self.results.get('sustained_load', {})
        if sustained:
            accuracy_status = "✅ GOOD" if sustained['rate_accuracy'] >= 90 else "⚠️  FAIR"
            logger.info(f"Sustained Load: {sustained['actual_rate']:.1f} ops/s {accuracy_status}")
            logger.info(f"  Rate accuracy: {sustained['rate_accuracy']:.1f}%")
        
        logger.info("="*50)


async def main():
    """Main benchmark function."""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Use temporary database for benchmarking
    benchmark = DatabaseBenchmark("sqlite+aiosqlite:///benchmark.db")
    
    try:
        results = await benchmark.run_full_benchmark()
        benchmark.print_summary()
        
        # Cleanup benchmark database
        import os
        if os.path.exists("benchmark.db"):
            os.remove("benchmark.db")
            
    except Exception as e:
        logger.error(f"Benchmark failed: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)