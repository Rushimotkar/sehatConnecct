import os
import sys
import json
import numpy as np
from dataclasses import dataclass
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    confusion_matrix
)

from src.logger import logging
from src.exception import CustomException
from src.utils.comman import load_object


@dataclass
class ModelEvaluationConfig:
    report_path: str = os.path.join(
        "artifacts", "evaluation_report.json"
    )


class ModelEvaluation:
    def __init__(self):
        self.config = ModelEvaluationConfig()

    def evaluate(self, X_test, y_test):
        try:
            logging.info(">>> Model Evaluation Started")

            # Load model
            model = load_object("artifacts/model.pkl")

            # Predict
            y_pred = model.predict(X_test)

            # Metrics
            report = {
                "accuracy" : round(accuracy_score(y_test, y_pred), 4),
                "precision": round(precision_score(
                    y_test, y_pred, average="weighted", zero_division=0), 4),
                "recall"   : round(recall_score(
                    y_test, y_pred, average="weighted", zero_division=0), 4),
                "f1_score" : round(f1_score(
                    y_test, y_pred, average="weighted", zero_division=0), 4),
            }

            # Save report
            os.makedirs(
                os.path.dirname(self.config.report_path),
                exist_ok=True
            )
            with open(self.config.report_path, "w") as f:
                json.dump(report, f, indent=4)

            logging.info(f"Evaluation Report: {report}")
            logging.info(
                f"Report saved → {self.config.report_path}"
            )
            logging.info(">>> Model Evaluation Completed ")

            return report

        except Exception as e:
            raise CustomException(e, sys)