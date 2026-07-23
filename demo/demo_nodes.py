"""Demo node implementations for the pipeline manager test workspace.

Provides concrete CachedSubprocess subclasses for the student data pipeline:
  StudentGenerator, AgeStats, HeightWeightStats, GenderStats, StudentReporter.
"""

import csv
import json
import os
import random

from pipeline_manager.pipeline import Pipeline, CachedSubprocess, Param


@Pipeline.register_node
class StudentGenerator(CachedSubprocess):
    """Generate random student data with name, gender, age, height, and weight."""

    def __init__(self, ctx, id=None):
        super().__init__(ctx, id)
        self.params = [
            Param(name="count", description="Number of students to generate",
                  value=10, param_type="int"),
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