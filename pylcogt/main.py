""" main.py: Main driver script for PyLCOGT.

    The main() function is a console entry point.

Author
    Curtis McCully (cmccully@lcogt.net)

October 2015
"""
from __future__ import absolute_import, print_function, division

import collections
import argparse
import sqlalchemy
from .utils import date_utils
from multiprocessing import Pool
from . import ingest
from . import dbs, logs
from . import bias, trim, dark, flats, astrometry, catalog


# A dictionary converting the string input by the user into the corresponding Python object
reduction_stages = collections.OrderedDict()
reduction_stages['ingest'] = ingest.Ingest
reduction_stages['make_bias'] = bias.MakeBias
reduction_stages['subtract_bias'] = bias.SubtractBias
reduction_stages['trim'] = trim.Trim
reduction_stages['make_dark'] = dark.MakeDark
reduction_stages['subtract_dark'] = dark.SubtractDark
reduction_stages['make_flat'] = flats.MakeFlat
reduction_stages['divide_flat'] = flats.DivideFlat
reduction_stages['solve_wcs'] = astrometry.Astrometry
reduction_stages['make_catalog'] = catalog.Catalog


def get_telescope_info():
    """
    Get information about the available telescopes/instruments from the database.

    Returns
    -------
    all_sites:  list
        List of all site codes, e.g. "lsc".
    all_instruments: list
        List of all instrument code, e.g. "kb78"
    all_telescope_ids: list
        List of all telescope IDs, e.g. "1m0-009"
    all_camera_types: list
        List of available camera types. e.g. "Sinistro" or "SBig"

    Notes
    -----
    The output of this function is used to limit what data is reduced and to validate use input.
"""
    db_session = dbs.get_session()

    all_sites = []
    for site in db_session.query(dbs.Telescope.site).distinct():
        all_sites.append(site[0])

    all_instruments = []
    for instrument in db_session.query(dbs.Telescope.instrument).distinct():
        all_instruments.append(instrument[0])

    all_telescope_ids = []
    for telescope_id in db_session.query(dbs.Telescope.telescope_id).distinct():
        all_telescope_ids.append(telescope_id[0])

    all_camera_types = []
    for camera_type in db_session.query(dbs.Telescope.camera_type).distinct():
        all_camera_types.append(camera_type[0])

    db_session.close()

    return all_sites, all_instruments, all_telescope_ids, all_camera_types


def main(cmd_args=None):
    """
    Main driver script for PyLCOGT. This is a console entry point.
    """
    import sys
    print(sys.argv)
    # Get the available instruments/telescopes
    all_sites, all_instruments, all_telescope_ids, all_camera_types = get_telescope_info()

    parser = argparse.ArgumentParser(description='Reduce LCOGT imaging data.')
    parser.add_argument("--epoch", required=True, type=str, help='Epoch to reduce')
    parser.add_argument("--telescope", default='', choices=all_telescope_ids,
                        help='Telescope ID (e.g. 1m0-010).')
    parser.add_argument("--instrument", default='', type=str, choices=all_instruments,
                        help='Instrument code (e.g. kb74)')
    parser.add_argument("--site", default='', type=str, choices=all_sites,
                        help='Site code (e.g. elp)')
    parser.add_argument("--camera-type", default='', type=str, choices=all_camera_types,
                        help='Camera type (e.g. sbig)')

    parser.add_argument("--stage", default='', choices=reduction_stages.keys(),
                        help='Reduction stages to run')

    parser.add_argument("--raw-path", default='/archive/engineering',
                        help='Top level directory where the raw data is stored')
    parser.add_argument("--processed-path", default='/nethome/supernova/pylcogt',
                        help='Top level directory where the processed data will be stored')

    parser.add_argument("--filter", default='', help="Image filter",
                        choices=['sloan', 'landolt', 'apass', 'up', 'gp', 'rp', 'ip', 'zs',
                                 'U', 'B', 'V', 'R', 'I'])

    parser.add_argument("--binning", default='', choices=['1x1', '2x2'],
                        help="Image binning (CCDSUM)")
    parser.add_argument("--image-type", default='', choices=['BIAS', 'DARK', 'SKYFLAT', 'EXPOSE'],
                        help="Image type to reduce.")

    parser.add_argument("--log-level", default='info', choices=['debug', 'info', 'warning',
                                                                'critical', 'fatal', 'error'])
    parser.add_argument("--ncpus", default=1, type=int,
                        help='Number of multiprocessing cpus to use.')

    args = parser.parse_args(cmd_args)

    logs.start_logging(log_level=args.log_level)

    # Get a list of dayobs to reduce
    epoch_list = date_utils.parse_epoch_string(args.epoch)

    reduction_stage_list = [i for i in reduction_stages.iterkeys()]
    if args.stage != '':
        if '-' in args.stage:

            starting_stage, ending_stage = args.stage.split('-')
            stages_to_do = reduction_stage_list[starting_stage: ending_stage + 1]
        else:
            stages_to_do = [args.stage]
    else:
        stages_to_do = reduction_stage_list

    # Get the telescopes for which we want to reduce data.
    db_session = dbs.get_session()

    telescope_query = sqlalchemy.sql.expression.true()

    if args.site != '':
        telescope_query &= dbs.Telescope.site == args.site

    if args.instrument != '':
        telescope_query &= dbs.Telescope.instrument == args.instrument

    if args.telescope != '':
        telescope_query &= dbs.Telescope.telescope_id == args.telescope

    if args.camera_type != '':
        telescope_query &= dbs.Telescope.camera_type == args.camera_type

    telescope_list = db_session.query(dbs.Telescope).filter(telescope_query).all()

    image_query = sqlalchemy.sql.expression.true()

    if args.filter != '':
        image_query &= dbs.Image.filter_name == args.filter

    if args.binning != '':
        ccdsum = args.binning.replace('x', ' ')
        image_query &= dbs.Image.ccdsum == ccdsum

    db_session.close()
    logger = logs.get_logger('Main')
    logger.info('Starting pylcogt:')

    for stage in stages_to_do:
        stage_to_run = reduction_stages[stage](args.raw_path, args.processed_path,
                                               image_query)
        stage_to_run.run(epoch_list, telescope_list)

    # Clean up
    logs.stop_logging()
