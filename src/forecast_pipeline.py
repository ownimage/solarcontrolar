import logging

from common.logging_setup import setup_logging

setup_logging()

from solar_forecast_generator import SolarForecastGenerator
from calc_error import CalcError
from config_generator import ConfigGenerator

logger = logging.getLogger(__name__)


def run():
    logger.info("forecast pipeline: start")
    logger.debug("stage 1/3: fetching solar forecast for tomorrow")
    SolarForecastGenerator().run()

    logger.debug("stage 2/3: comparing recent forecasts with actuals")
    CalcError().run()

    logger.debug("stage 3/3: working out battery charge level for tomorrow")
    ConfigGenerator().run()

    logger.info("forecast pipeline: complete")


if __name__ == '__main__':
    run()