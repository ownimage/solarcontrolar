from usage_actuals import UsageActuals
from solar_forecast_generator import SolarForecastGenerator
from solar_actuals import SolarActualsUpdater
from calc_error import CalcError
from config_generator import ConfigGenerator


if __name__ == '__main__':
    SolarForecastGenerator().run()
    CalcError().run()
    ConfigGenerator().run()
