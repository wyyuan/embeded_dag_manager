import random
import csv
import json
import os
from pipeline import Context, CachedSubprocess, Input, Output, Param, register_node


@register_node
class StudentGenerator(CachedSubprocess):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.name = "StudentGenerator"
        self.outputs = [Output(name="students", description="Generated student list")]
        self.params = [Param(name="count", description="Number of students to generate", value=10, param_type="int")]

    def _execute(self):
        first_names = ["Alice", "Bob", "Charlie", "Diana", "Eve", "Frank", "Grace", "Henry", "Iris", "Jack",
                       "Kate", "Leo", "Mary", "Nick", "Olivia", "Paul", "Quinn", "Rose", "Sam", "Tina"]
        last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez",
                      "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore"]
        genders = ["M", "F"]

        count = next((p.value for p in self.params if p.name == "count"), 10)

        students = []
        for i in range(count):
            student = {
                "id": f"S{i+1:04d}",
                "name": f"{random.choice(first_names)} {random.choice(last_names)}",
                "gender": random.choice(genders),
                "age": random.randint(18, 25),
                "height": round(random.uniform(160, 190), 1),
                "weight": round(random.uniform(50, 90), 1)
            }
            students.append(student)

        output_file = self.cache_path("students.csv")
        with open(output_file, "w", newline="", encoding="utf-8") as f:
            if students:
                writer = csv.DictWriter(f, fieldnames=["id", "name", "gender", "age", "height", "weight"])
                writer.writeheader()
                writer.writerows(students)

        print(f"  Generated {len(students)} students, saved to {output_file}")


@register_node
class AgeStats(CachedSubprocess):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.name = "AgeStats"
        self.inputs = [Input(name="students", description="Student list from generator")]
        self.outputs = [Output(name="age_stats", description="Age statistics")]

    def _execute(self):
        students_input = self.get_input("students")
        if not students_input or not students_input.path:
            raise ValueError("Input 'students' path not set")

        students = []
        with open(students_input.path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                row["age"] = int(row["age"])
                students.append(row)

        ages = [s["age"] for s in students]
        stats = {
            "count": len(ages),
            "min": min(ages),
            "max": max(ages),
            "avg": round(sum(ages) / len(ages), 2)
        }

        output_file = self.cache_path("age_stats.csv")
        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["count", "min", "max", "avg"])
            writer.writeheader()
            writer.writerow(stats)

        print(f"  Age stats: min={stats['min']}, max={stats['max']}, avg={stats['avg']}")


@register_node
class HeightWeightStats(CachedSubprocess):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.name = "HeightWeightStats"
        self.inputs = [Input(name="students", description="Student list from generator")]
        self.outputs = [Output(name="hw_stats", description="Height and weight statistics")]

    def _execute(self):
        students_input = self.get_input("students")
        if not students_input or not students_input.path:
            raise ValueError("Input 'students' path not set")

        students = []
        with open(students_input.path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                row["height"] = float(row["height"])
                row["weight"] = float(row["weight"])
                students.append(row)

        heights = [s["height"] for s in students]
        weights = [s["weight"] for s in students]

        stats = {
            "height_min": min(heights),
            "height_max": max(heights),
            "height_avg": round(sum(heights)/len(heights), 1),
            "weight_min": min(weights),
            "weight_max": max(weights),
            "weight_avg": round(sum(weights)/len(weights), 1)
        }

        output_file = self.cache_path("hw_stats.csv")
        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["height_min", "height_max", "height_avg", "weight_min", "weight_max", "weight_avg"])
            writer.writeheader()
            writer.writerow(stats)

        print(f"  Height avg: {stats['height_avg']}cm, Weight avg: {stats['weight_avg']}kg")


@register_node
class GenderStats(CachedSubprocess):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.name = "GenderStats"
        self.inputs = [Input(name="students", description="Student list from generator")]
        self.outputs = [Output(name="gender_stats", description="Gender distribution statistics")]

    def _execute(self):
        students_input = self.get_input("students")
        if not students_input or not students_input.path:
            raise ValueError("Input 'students' path not set")

        students = []
        with open(students_input.path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            students = list(reader)

        male_count = sum(1 for s in students if s["gender"] == "M")
        female_count = sum(1 for s in students if s["gender"] == "F")

        stats = {
            "male": male_count,
            "female": female_count,
            "ratio": round(male_count / female_count, 2) if female_count > 0 else None
        }

        output_file = self.cache_path("gender_stats.csv")
        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["male", "female", "ratio"])
            writer.writeheader()
            writer.writerow(stats)

        print(f"  Male: {male_count}, Female: {female_count}")


@register_node
class StudentReporter(CachedSubprocess):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.name = "StudentReporter"
        self.inputs = [
            Input(name="students", description="Student list"),
            Input(name="age_stats", description="Age statistics"),
            Input(name="hw_stats", description="Height/weight statistics"),
            Input(name="gender_stats", description="Gender statistics")
        ]
        self.outputs = [Output(name="report", description="Final comprehensive report")]

    def _execute(self):
        students_input = self.get_input("students")
        age_input = self.get_input("age_stats")
        hw_input = self.get_input("hw_stats")
        gender_input = self.get_input("gender_stats")

        if not students_input or not students_input.path:
            raise ValueError("Input 'students' path not set")
        if not age_input or not age_input.path:
            raise ValueError("Input 'age_stats' path not set")
        if not hw_input or not hw_input.path:
            raise ValueError("Input 'hw_stats' path not set")
        if not gender_input or not gender_input.path:
            raise ValueError("Input 'gender_stats' path not set")

        students = []
        with open(students_input.path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            students = list(reader)

        age_stats = {}
        with open(age_input.path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            age_stats = next(reader)
            age_stats = {k: int(v) if k != 'avg' else float(v) for k, v in age_stats.items()}

        hw_stats = {}
        with open(hw_input.path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            hw_stats = next(reader)
            hw_stats = {k: float(v) for k, v in hw_stats.items()}

        gender_stats = {}
        with open(gender_input.path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            gender_stats = next(reader)
            gender_stats = {k: int(v) if k != 'ratio' else (float(v) if v else None) for k, v in gender_stats.items()}

        report = {
            "total_students": len(students),
            "age_statistics": age_stats,
            "height_weight_statistics": hw_stats,
            "gender_statistics": gender_stats,
            "sample_students": students[:3]
        }

        output_file = self.cache_path("report.json")
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        print(f"  Report generated: {len(students)} students analyzed")