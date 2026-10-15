"""
Pipeline:
train/test array ->
split X, y ->
train models ->
evaluate ->
select best ->
save model ->
return accuracy
"""

import os
import sys
import numpy as np
from dataclasses import dataclass

# Models
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import (
    RandomForestClassifier,
    GradientBoostingClassifier,
    AdaBoostClassifier
)
from sklearn.neighbors import KNeighborsClassifier
from sklearn.svm import SVC

# Metrics
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import GridSearchCV

# Custom
from src.logger import logging
from src.exception import CustomException
from src.utils.comman import save_object


# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────
@dataclass
class ModelTrainerConfig:
    trained_model_path: str = os.path.join("artifacts", "model.pkl")
    expected_accuracy: float = 0.6


# ─────────────────────────────────────────
# MAIN CLASS
# ─────────────────────────────────────────
class ModelTrainer:
    def __init__(self):
        self.config = ModelTrainerConfig()

    # ─────────────────────────────────────
    # EVALUATE MODELS
    # ─────────────────────────────────────
    def evaluate_model(self, X_train, y_train, X_test, y_test, models, params):
        try:
            report = {}            #  stores accuracy
            trained_models = {}   #  stores trained models

            for name, model in models.items():
                logging.info(f"Training model: {name}")

                param_grid = params.get(name, {})

                # Hyperparameter tuning
                if param_grid:
                    gs = GridSearchCV(
                        model,
                        param_grid,
                        cv=3,
                        scoring="accuracy",
                        n_jobs=-1
                    )
                    gs.fit(X_train, y_train)
                    best_model = gs.best_estimator_

                    logging.info(f"{name} best params: {gs.best_params_}")
                else:
                    best_model = model
                    best_model.fit(X_train, y_train)

                # Prediction
                y_pred = best_model.predict(X_test)

                # Accuracy
                acc = accuracy_score(y_test, y_pred)

                report[name] = acc
                trained_models[name] = best_model

                logging.info(f"{name} -> Accuracy: {acc:.4f}")
                logging.info(f"\n{classification_report(y_test, y_pred)}")

            return report, trained_models

        except Exception as e:
            raise CustomException(e, sys)

    # ─────────────────────────────────────
    # MAIN TRAINING
    # ─────────────────────────────────────
    def initiate_model_training(self, train_arr, test_arr):
        try:
            # Split data
            X_train = train_arr[:, :-1]
            y_train = train_arr[:, -1]

            X_test = test_arr[:, :-1]
            y_test = test_arr[:, -1]

            logging.info(f"X_train: {X_train.shape}, y_train: {y_train.shape}")
            logging.info(f"X_test: {X_test.shape}, y_test: {y_test.shape}")

            # Models
            models = {
                "Logistic Regression": LogisticRegression(max_iter=1000),
                "Decision Tree": DecisionTreeClassifier(),
                "Random forest": RandomForestClassifier(),
                "Gradient boosting": GradientBoostingClassifier(),
                "AdaBoost": AdaBoostClassifier(),
                "KNN": KNeighborsClassifier(),
                "SVM": SVC()
            }

            # Hyperparameters
            params = {
                "Logistic Regression": {
                    "C": [0.01, 0.1, 1, 10],   #  fixed
                    "solver": ["lbfgs", "liblinear"]
                },
                "Random forest": {
                    "n_estimators": [50, 100, 200],
                    "max_depth": [5, 10, None]
                },
                "Gradient boosting": {   #  name fixed
                    "n_estimators": [50, 100],
                    "learning_rate": [0.05, 0.1, 0.2],
                    "max_depth": [3, 5]
                },
                "AdaBoost": {
                    "n_estimators": [50, 100],
                    "learning_rate": [0.5, 1.0]
                },
                "KNN": {
                    "n_neighbors": [3, 5, 7, 11],
                    "weights": ["uniform", "distance"]
                },
                "SVM": {
                    "C": [0.1, 1, 10],
                    "kernel": ["linear", "rbf"]
                }
            }

            logging.info("Evaluating models...")

            # Evaluate
            model_report, trained_models = self.evaluate_model(
                X_train, y_train, X_test, y_test, models, params
            )

            # Print report
            logging.info("\n" + "=" * 50)
            logging.info("MODEL REPORT")
            logging.info("=" * 50)

            for name, score in sorted(
                model_report.items(),
                key=lambda x: x[1],
                reverse=True
            ):
                logging.info(f"{name:<25} -> {score:.4f}")

            logging.info("=" * 50)

            # Best model (OUTSIDE LOOP )
            best_model_name = max(model_report, key=model_report.get)
            best_model_score = model_report[best_model_name]
            best_model = trained_models[best_model_name]

            logging.info(f"Best Model: {best_model_name}")
            logging.info(f"Best Score: {best_model_score:.4f}")

            # Accuracy check
            if best_model_score < self.config.expected_accuracy:
                raise CustomException(
                    f"No model met accuracy threshold ({self.config.expected_accuracy})",
                    sys
                )

            # Final evaluation
            y_pred = best_model.predict(X_test)
            final_acc = accuracy_score(y_test, y_pred)

            logging.info(f"Final Accuracy: {final_acc:.4f}")
            logging.info(f"\n{classification_report(y_test, y_pred)}")

            # Save model
            save_object(
                file_path=self.config.trained_model_path,
                obj=best_model
            )

            logging.info(f"Model saved at {self.config.trained_model_path}")
            logging.info("Training Completed ")

            return final_acc, best_model_name

        except Exception as e:
            raise CustomException(e, sys)