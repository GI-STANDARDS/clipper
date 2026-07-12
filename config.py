from dataclasses import dataclass


@dataclass
class Config:
    output_dir: str = "output"
    csv_path: str = "time.csv"
