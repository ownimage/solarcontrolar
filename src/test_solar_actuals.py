import json

if __name__ == '__main__':
    # Load the JSON data
    with open('usage_actuals-1.json', 'r') as f:
        data = json.load(f)

    # Calculate and print daily totals
    for date, times in data.items():
        total = sum(times.values())
        print(f"{date}: {total:.4f}")