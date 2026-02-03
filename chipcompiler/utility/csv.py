#!/usr/bin/env python

import csv


def csv_write(file_path: str, header, data) -> bool:
    with open(file_path, "w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        # writer = csv.DictWriter(csvfile)

        writer.writerows(header)
        writer.writerows(data)

        return True

        # Write headers
        writer.writeheader()

        # Write data rows
        for workspace_data in data:
            row = {}
            # Add counts for each layer, defaulting to 0 if not present

            for idnex, item in enumerate(workspace_data):
                row[header[idnex]] = item
            writer.writerow(row)

        return True
    return False
