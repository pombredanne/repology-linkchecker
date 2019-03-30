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
import sys

import aiopg

from linkchecker.processor.dummy import DummyUrlProcessor
from linkchecker.queries import iterate_urls_to_recheck
from linkchecker.worker import HostWorkerPool


async def main_loop(options: argparse.Namespace, pgpool: aiopg.Pool) -> None:
    url_processor = DummyUrlProcessor(pgpool)

    while True:
        worker_pool = HostWorkerPool(url_processor)

        # process all urls which need processing
        async for url in iterate_urls_to_recheck(pgpool, datetime.timedelta(seconds=options.recheck_age)):
            await worker_pool.add_url(url)

        # make sure all results land in the database before next iteration
        await worker_pool.join()

        if worker_pool.stats.consumed:
            print(
                'Run finished: {} urls total, {} processed, {} postponed'.format(
                    worker_pool.stats.consumed,
                    worker_pool.stats.processed,
                    worker_pool.stats.dropped,
                ),
                file=sys.stderr
            )

        if options.single_run:
            return

        if not worker_pool.stats.consumed:
            # sleep a bit if there were no urls to process
            await asyncio.sleep(10)


def parse_arguments() -> argparse.Namespace:
    config = {
        'DSN': 'dbname=repology user=repology password=repology',
    }

    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--dsn', default=config['DSN'], help='database connection params')

    parser.add_argument('--recheck-age', type=int, default=604800, help='min age for recheck in seconds')

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
