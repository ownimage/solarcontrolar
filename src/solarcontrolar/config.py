import json
import copy


class Config:

    def __init__(self, filename="config.json", data=None):
        self.__filename = filename

        if data is None:
            with open(filename, "r") as file:
                self.__data = json.load(file)
        else:
            self.__data = data

    def get_data(self):
        return copy.deepcopy(self.__data)

    def save(self):
        with open(self.__filename, "w") as file:
            json.dump(self.__data, file, indent=4)
