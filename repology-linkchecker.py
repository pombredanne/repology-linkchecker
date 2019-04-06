#!/usr/bin/env python3
#
# Copyright (C) 2019 Dmitry Marakasov <amdmi3@amdmi3.ru>
#
# This file is part of repology
#
# repology is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# repology is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with repology.  If not, see <http://www.gnu.org/licenses/>.

import argparse
import asyncio
import datetime
import signal
import sys
from typing import Any

import aiopg

from linkchecker.delay import DelayManager
from linkchecker.processor.dispatching import DispatchingUrlProcessor
from linkchecker.processor.dummy import DummyUrlProcessor
from linkchecker.processor.http import HttpUrlProcessor
from linkchecker.queries import iterate_urls_to_recheck
from linkchecker.worker import HostWorkerPool


try:
    from signal import SIGINFO
    SIGINFO_SUPPORTED = True
except ImportError:
    SIGINFO_SUPPORTED = False


async def main_loop(options: argparse.Namespace, pgpool: aiopg.Pool) -> None:
    delay_manager = DelayManager(options.delay)

    dummy_processor = DummyUrlProcessor(pgpool)
    http_processor = HttpUrlProcessor(pgpool, delay_manager, options.timeout)
    dispatcher = DispatchingUrlProcessor(dummy_processor, http_processor)

    worker_pool = HostWorkerPool(dispatcher)

    run_number = 0

    def print_statistics(*args: Any) -> None:
        stats = worker_pool.get_statistics()

        print(
            'Run #{} finished: {} urls scanned, {} submitted for processing, {} processed'.format(
                run_number,
                stats.scanned,
                stats.submitted,
                stats.processed
            ),
            file=sys.stderr
        )

    if SIGINFO_SUPPORTED:
        signal.signal(SIGINFO, print_statistics)

    while True:
        run_number += 1
        worker_pool.reset_statistics()

        # process all urls which need processing
        async for url in iterate_urls_to_recheck(pgpool, datetime.timedelta(seconds=options.recheck_age)):
            await worker_pool.add_url(url)

        print_statistics()

        if options.single_run:
            await worker_pool.join()
            return

        await asyncio.sleep(60)


def parse_arguments() -> argparse.Namespace:
    config = {
        'DSN': 'dbname=repology user=repology password=repology',
    }

    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--dsn', default=config['DSN'], help='database connection params')

    parser.add_argument('--recheck-age', type=int, default=604800, help='min age for recheck in seconds')
    parser.add_argument('--delay', type=float, default=3.0, help='delay between requests to the same host')
    parser.add_argument('--timeout', type=int, default=60, help='timeout for each check')

    parser.add_argument('--max-host-workers', type=int, default=100, help='maximum number of parallel host workers')
    parser.add_argument('--max-host-queue', type=int, default=100, help='maximum depth of per-host url queue')

    parser.add_argument('--single-run', action='store_true', help='exit after single run')

    return parser.parse_args()


async def main() -> None:
    options = parse_arguments()

    async with aiopg.create_pool(options.dsn) as pgpool:
        await main_loop(options, pgpool)


if __name__ == '__main__':
    asyncio.run(main())
