"""Demo node implementations for the pipeline manager test workspace.

All nodes use the declarative trait-injection style: ``inputs`` / ``outputs`` /
``params`` are declared as class-level attributes and ``@Pipeline.register_node``
deep-copies them into each instance.  No ``__init__`` boilerplate is needed —
the decorator handles ``id`` assignment and trait injection automatically.
"""

import csv
import json
import os
import random

from pipeline_manager.pipeline import (
    Pipeline, CachedSubprocess, Param, Input, Output, Context
)


@Pipeline.register_node
class CloneSolution(CachedSubprocess):
    """Clone a solution JSON into N files, one per multiplier."""

    inputs = [
        Input("solution_json", description="Source solution JSON file"),
    ]
    outputs = [
        Output("clones", description="Folder containing cloned JSON files"),
    ]
    params = [
        Param("multiplier",
              description="Number of clones to produce",
              value=3,
              param_type="int"),
    ]

    def _execute(self):
        source = self.require_input("solution_json")

        multiplier = 1
        for p in self.params:
            if p.name == "multiplier" and p.value is not None:
                multiplier = int(p.value)

        with open(source, "r", encoding="utf-8") as f:
            data = json.load(f)

        out_dir = self.cache_folder()
        os.makedirs(out_dir, exist_ok=True)

        for i in range(1, multiplier + 1):
            clone_path = os.path.join(out_dir, f"clone_{i:03d}.json")
            cloned = json.loads(json.dumps(data))
            cloned["clone_index"] = i
            with open(clone_path, "w", encoding="utf-8") as f:
                json.dump(cloned, f, ensure_ascii=False, indent=2)

        print(f"  Cloned solution JSON x{multiplier} -> {out_dir}")


@Pipeline.register_node
class StudentGenerator(CachedSubprocess):
    """Generate random student data with name, gender, age, height, and weight."""

    outputs = [
        Output("students", description="CSV of generated student records"),
    ]
    params = [
        Param("count",
              description="Number of students to generate",
              value=10,
              param_type="int"),
    ]

    def _execute(self):
        count = 10
        for p in self.params:
            if p.name == "count" and p.value is not None:
                count = int(p.value)

        first_names = [
            "Alice", "Bob", "Charlie", "Diana", "Eve", "Frank", "Grace",
            "Henry", "Iris", "Jack", "Kate", "Leo", "Mia", "Noah", "Olivia",
            "Paul", "Quinn", "Rose", "Sam", "Tina", "Uma", "Victor", "Wendy",
        ]
        last_names = [
            "Smith", "Jones", "Williams", "Brown", "Miller", "Garcia",
            "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Lee",
        ]

        output_path = self.cache_path("students.csv")
        os.makedirs(self.cache_folder(), exist_ok=True)

        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["id", "name", "gender", "age", "height", "weight"])
            for i in range(1, count + 1):
                first = random.choice(first_names)
                last = random.choice(last_names)
                gender = random.choice(["M", "F"])
                age = random.randint(18, 25)
                height = round(random.uniform(155, 195), 1)
                weight = round(random.uniform(45, 95), 1)
                writer.writerow([f"S{i:04d}", f"{first} {last}", gender, age, height, weight])

        print(f"  Generated {count} students, saved to {output_path}")


@Pipeline.register_node
class AgeStats(CachedSubprocess):
    """Calculate age statistics (min, max, avg) from student data."""

    inputs = [
        Input("students", description="CSV of student records"),
    ]
    outputs = [
        Output("age_stats", description="CSV with count/min/max/avg ages"),
    ]

    def _execute(self):
        input_path = self.require_input("students")

        ages = []
        with open(input_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ages.append(int(row["age"]))

        count = len(ages)
        min_age = min(ages) if ages else 0
        max_age = max(ages) if ages else 0
        avg_age = round(sum(ages) / count, 1) if ages else 0

        output_path = self.cache_path("age_stats.csv")
        os.makedirs(self.cache_folder(), exist_ok=True)
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["count", "min", "max", "avg"])
            writer.writerow([count, min_age, max_age, avg_age])

        print(f"  Age stats: min={min_age}, max={max_age}, avg={avg_age}")


@Pipeline.register_node
class HeightWeightStats(CachedSubprocess):
    """Calculate height and weight statistics from student data."""

    inputs = [
        Input("students", description="CSV of student records"),
    ]
    outputs = [
        Output("hw_stats", description="CSV with height/weight min/max/avg"),
    ]

    def _execute(self):
        input_path = self.require_input("students")

        heights = []
        weights = []
        with open(input_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                heights.append(float(row["height"]))
                weights.append(float(row["weight"]))

        h_min = min(heights) if heights else 0
        h_max = max(heights) if heights else 0
        h_avg = round(sum(heights) / len(heights), 1) if heights else 0
        w_min = min(weights) if weights else 0
        w_max = max(weights) if weights else 0
        w_avg = round(sum(weights) / len(weights), 1) if weights else 0

        output_path = self.cache_path("hw_stats.csv")
        os.makedirs(self.cache_folder(), exist_ok=True)
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["height_min", "height_max", "height_avg",
                             "weight_min", "weight_max", "weight_avg"])
            writer.writerow([h_min, h_max, h_avg, w_min, w_max, w_avg])

        print(f"  Height avg: {h_avg}cm, Weight avg: {w_avg}kg")


@Pipeline.register_node
class GenderStats(CachedSubprocess):
    """Calculate gender distribution statistics from student data."""

    inputs = [
        Input("students", description="CSV of student records"),
    ]
    outputs = [
        Output("gender_stats", description="CSV with male/female counts and ratio"),
    ]

    def _execute(self):
        input_path = self.require_input("students")

        male = 0
        female = 0
        with open(input_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                gender = row["gender"].strip().upper()
                if gender == "M":
                    male += 1
                elif gender == "F":
                    female += 1

        total = male + female
        ratio = round(male / female, 1) if female > 0 else (male if male > 0 else 0)

        output_path = self.cache_path("gender_stats.csv")
        os.makedirs(self.cache_folder(), exist_ok=True)
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["male", "female", "ratio"])
            writer.writerow([male, female, ratio])

        print(f"  Male: {male}, Female: {female}")


@Pipeline.register_node
class StudentReporter(CachedSubprocess):
    """Generate comprehensive report combining all statistics."""

    inputs = [
        Input("students", description="CSV of student records"),
        Input("age_stats", description="CSV of age statistics"),
        Input("hw_stats", description="CSV of height/weight statistics"),
        Input("gender_stats", description="CSV of gender statistics"),
    ]
    outputs = [
        Output("report", description="Combined JSON report"),
    ]

    def _execute(self):
        students_path = self.require_input("students")
        age_path = self.require_input("age_stats")
        hw_path = self.require_input("hw_stats")
        gender_path = self.require_input("gender_stats")

        # Read students
        students = []
        with open(students_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                students.append(row)

        # Read age stats
        with open(age_path, "r", encoding="utf-8") as f:
            age_row = next(csv.DictReader(f))

        # Read height/weight stats
        with open(hw_path, "r", encoding="utf-8") as f:
            hw_row = next(csv.DictReader(f))

        # Read gender stats
        with open(gender_path, "r", encoding="utf-8") as f:
            gender_row = next(csv.DictReader(f))

        report = {
            "total_students": len(students),
            "age_statistics": {
                "count": int(age_row["count"]),
                "min": int(age_row["min"]),
                "max": int(age_row["max"]),
                "avg": float(age_row["avg"]),
            },
            "height_weight_statistics": {
                "height_min": float(hw_row["height_min"]),
                "height_max": float(hw_row["height_max"]),
                "height_avg": float(hw_row["height_avg"]),
                "weight_min": float(hw_row["weight_min"]),
                "weight_max": float(hw_row["weight_max"]),
                "weight_avg": float(hw_row["weight_avg"]),
            },
            "gender_statistics": {
                "male": int(gender_row["male"]),
                "female": int(gender_row["female"]),
                "ratio": float(gender_row["ratio"]),
            },
            "sample_students": students[:3],
        }

        output_path = self.cache_path("report.json")
        os.makedirs(self.cache_folder(), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        print(f"  Report generated: {len(students)} students analyzed")
