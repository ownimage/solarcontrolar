from datetime import date, timedelta


class DateHelper:
    def __init__(self, date=date.today()):
        self.date = date

    def today(self):
        return self.date

    def today_iso(self):
        return self.today().isoformat()

    def today_day(self):
        return self.today().strftime('%A')

    def tomorrow(self):
        return self.offset(1)

    def tomorrow_iso(self):
        return self.tomorrow().isoformat()

    def tomorrow_day(self):
        return self.tomorrow().strftime('%A')

    def offset(self, days=1):
        return self.date + timedelta(days=days)

    def offset_iso(self, days=1):
        return self.offset(days=days).isoformat()

    def offset_day(self, days=1):
        return self.offset(days=days).strftime('%A')




