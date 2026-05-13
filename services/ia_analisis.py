import importlib.util
import json
import logging
import traceback
from pathlib import Path
from zipfile import ZipFile


LOGGER = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
BACKEND_MODELS_DIR = BASE_DIR / "models"

DEFAULT_METADATA = {
    "image_size": [160, 160],
    "target_classes": ["cancer_cervicouterino", "frotis_normal", "vph"],
    "stage1_class_names": ["frotis_normal", "anormal"],
    "stage2_class_names": ["cancer_cervicouterino", "vph"],
    "display_names": {
        "cancer_cervicouterino": "Cancer cervicouterino",
        "frotis_normal": "Frotis normal",
        "vph": "VPH",
        "anormal": "Anormal",
        "en_revision": "Analisis en revision",
    },
    "risk_map": {
        "cancer_cervicouterino": "Alto",
        "frotis_normal": "Bajo",
        "vph": "Medio",
        "anormal": "En revision",
        "en_revision": "En revision",
    },
    "summary_map": {
        "cancer_cervicouterino": "La imagen se parece mas a patrones citologicos asociados a cancer cervicouterino o lesiones de alto riesgo.",
        "frotis_normal": "La imagen se parece mas a un patron citologico normal dentro de este esquema de entrenamiento.",
        "vph": "La imagen se parece mas a patrones citologicos asociados a VPH.",
        "anormal": "La imagen se parece mas a un patron anormal y requiere clasificacion de la segunda etapa.",
        "en_revision": "La prediccion no alcanza un nivel suficiente de confianza o separacion entre clases para comunicarse como clasificacion automatica confiable.",
    },
    "recommendation_map": {
        "cancer_cervicouterino": "Requiere revision profesional prioritaria. Esta salida no reemplaza un diagnostico medico.",
        "frotis_normal": "Mantener interpretacion profesional segun el contexto clinico y la calidad de la muestra.",
        "vph": "Correlacionar con revision profesional y pruebas complementarias.",
        "anormal": "Continuar con revision profesional y correlacionar la muestra con la segunda etapa de clasificacion.",
        "en_revision": "Revisar manualmente la imagen y correlacionar con el contexto clinico antes de comunicar una conclusion.",
    },
    "normalize_to_unit_interval": False,
    "thresholds": {
        "stage1_normal_confidence_threshold": 0.48,
        "stage1_anormal_confidence_threshold": 0.58,
        "stage1_review_threshold": 0.50,
        "stage1_min_margin": 0.05,
        "stage2_confidence_threshold": 0.84,
        "stage2_review_threshold": 0.58,
        "stage2_min_margin": 0.14,
        "stage2_cancer_confidence_threshold": 0.80,
        "stage2_cancer_min_margin": 0.10,
        "stage2_vph_confidence_threshold": 0.94,
        "stage2_vph_min_margin": 0.22,
        "stage2_cancer_from_vph_min_probability": 0.32,
        "stage2_cancer_from_vph_max_margin": 0.18,
        "stage2_cancer_override_confidence": 0.88,
        "stage2_cancer_override_margin": 0.12,
        "stage2_vph_override_confidence": 0.97,
        "stage2_vph_override_margin": 0.28,
    },
    "blocked_label": "Analisis en revision",
    "blocked_summary": (
        "La imagen no cumple criterios minimos de confianza para una clasificacion automatica "
        "confiable. Puede tratarse de una muestra fuera del dominio citologico esperado, una captura de "
        "baja calidad o un patron insuficientemente representado en el entrenamiento."
    ),
    "blocked_recommendation": (
        "Revisar manualmente la imagen, verificar que corresponda a una muestra citologica adecuada y "
        "repetir la captura o el estudio si es necesario."
    ),
}


def _candidate_paths(*relative_names):
    for relative_name in relative_names:
        candidate = BACKEND_MODELS_DIR / relative_name
        if candidate.exists():
            return candidate
    return None


def _all_candidate_paths(*relative_names):
    candidates = []
    for relative_name in relative_names:
        candidate = BACKEND_MODELS_DIR / relative_name
        if candidate.exists():
            candidates.append(candidate)
    return candidates


def _keras_archive_requires_raw_pixels(keras_path):
    try:
        with ZipFile(keras_path, "r") as archive:
            config_text = archive.read("config.json").decode("utf-8")
    except Exception:
        return False

    return '"class_name": "TrueDivide"' in config_text and '"class_name": "Subtract"' in config_text


def _bundle_requires_raw_pixels():
    keras_archives = _all_candidate_paths(
        "citosmart_stage1_normal_vs_anormal.keras",
        "citosmart_stage2_vph_vs_cacu.keras",
        "citosmart_model_3clases.keras",
        "citosmart_model.keras",
    )
    for keras_archive in keras_archives:
        if keras_archive.suffix == ".keras" and _keras_archive_requires_raw_pixels(keras_archive):
            return True
    return False


def _deep_merge(base, extra):
    merged = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _sanitize_metadata(metadata):
    display_names = metadata.get("display_names", {})
    summary_map = metadata.get("summary_map", {})
    recommendation_map = metadata.get("recommendation_map", {})
    risk_map = metadata.get("risk_map", {})

    metadata["display_names"] = {
        str(key).lower().strip(): value for key, value in display_names.items()
    }
    metadata["summary_map"] = {
        str(key).lower().strip(): value for key, value in summary_map.items()
    }
    metadata["recommendation_map"] = {
        str(key).lower().strip(): value for key, value in recommendation_map.items()
    }
    metadata["risk_map"] = {
        str(key).lower().strip(): value for key, value in risk_map.items()
    }
    return metadata


def _find_config_path():
    return _candidate_paths(
        "citosmart_two_stage_config.json",
        "citosmart_model_3clases_config.json",
    )


def _load_metadata():
    metadata = dict(DEFAULT_METADATA)
    config_path = _find_config_path()
    if config_path and config_path.exists():
        with config_path.open("r", encoding="utf-8") as config_file:
            metadata = _deep_merge(metadata, json.load(config_file))
    if _bundle_requires_raw_pixels():
        metadata["normalize_to_unit_interval"] = False
    return _sanitize_metadata(metadata)


def _detect_model_bundle():
    stage1_path = _candidate_paths("citosmart_stage1_normal_vs_anormal.keras")
    stage2_path = _candidate_paths("citosmart_stage2_vph_vs_cacu.keras")
    if stage1_path and stage2_path:
        return {"kind": "two_stage", "stage1_path": stage1_path, "stage2_path": stage2_path}

    single_path = _candidate_paths("citosmart_model_3clases.keras")
    if single_path:
        return {"kind": "single_stage", "path": single_path}

    return None


class CytologyPredictor:
    def __init__(self):
        self.metadata = _load_metadata()
        self.model_bundle = _detect_model_bundle()
        self.model = None
        self.stage1_model = None
        self.stage2_model = None
        self.model_error = None
        self.model_path = None
        self._loaded = False

    def _ensure_loaded(self):
        if self._loaded:
            return

        self._loaded = True

        if self.model_bundle is None:
            self.model_error = (
                "No se encontro un archivo de modelo. Guarda los modelos exportados dentro de models/."
            )
            LOGGER.error(self.model_error)
            return

        if importlib.util.find_spec("tensorflow") is None:
            self.model_error = "TensorFlow no esta instalado en este entorno."
            LOGGER.error(self.model_error)
            return

        try:
            import tensorflow as tf
        except Exception as exc:
            self.model_error = f"No se pudo importar TensorFlow: {exc}"
            LOGGER.exception("Fallo importando TensorFlow")
            return

        try:
            if self.model_bundle["kind"] == "two_stage":
                self.stage1_model = tf.keras.models.load_model(
                    self.model_bundle["stage1_path"],
                    compile=False,
                )
                self.stage2_model = tf.keras.models.load_model(
                    self.model_bundle["stage2_path"],
                    compile=False,
                )
                self.model_path = {
                    "stage1": str(self.model_bundle["stage1_path"]),
                    "stage2": str(self.model_bundle["stage2_path"]),
                }
            else:
                self.model = tf.keras.models.load_model(
                    self.model_bundle["path"],
                    compile=False,
                )
                self.model_path = str(self.model_bundle["path"])
        except Exception as exc:
            self.model_error = f"No se pudo cargar el modelo: {exc}"
            LOGGER.exception("Fallo cargando el bundle de modelos")

    def _preprocess_image(self, image_path):
        if importlib.util.find_spec("numpy") is None:
            raise RuntimeError("Numpy no esta instalado.")
        if importlib.util.find_spec("PIL") is None:
            raise RuntimeError("Pillow no esta instalado.")

        import numpy as np
        from PIL import Image

        width, height = self.metadata.get("image_size", [160, 160])
        image = Image.open(image_path).convert("RGB").resize((width, height))
        array = np.asarray(image, dtype="float32")
        if self.metadata.get("normalize_to_unit_interval", True):
            array = array / 255.0
        return np.expand_dims(array, axis=0)

    def _display_label(self, raw_label):
        label = str(raw_label).lower().strip()
        return self.metadata.get("display_names", {}).get(label, raw_label)

    def _format_probability_entries(self, entries):
        formatted = []
        for entry in entries:
            label = str(entry["label"]).lower().strip()
            formatted.append(
                {
                    "label": label,
                    "display_name": self._display_label(label),
                    "probability": round(float(entry["probability"]) * 100, 2),
                }
            )
        return formatted

    def _decode_prediction(self, prediction, class_names):
        import numpy as np

        prediction = np.asarray(prediction).squeeze()
        ranked = []
        for index, probability in enumerate(prediction.tolist()):
            label = class_names[index] if index < len(class_names) else str(index)
            ranked.append({"label": label, "probability": float(probability)})
        ranked.sort(key=lambda item: item["probability"], reverse=True)
        top_prediction = ranked[0]
        return top_prediction["label"], top_prediction["probability"], ranked

    def _format_result(self, raw_label, confidence, probabilities, stage_details=None):
        label = str(raw_label).lower().strip()
        risk_map = self.metadata.get("risk_map", {})
        summary_map = self.metadata.get("summary_map", {})
        recommendation_map = self.metadata.get("recommendation_map", {})

        return {
            "clasificacion": self._display_label(label),
            "nivel_riesgo": risk_map.get(label, "En revision"),
            "confianza": f"{confidence * 100:.2f}%",
            "resumen": summary_map.get(label, "Prediccion generada por el pipeline configurado."),
            "recomendacion": recommendation_map.get(
                label,
                "Correlacionar la salida del modelo con el criterio del profesional tratante.",
            ),
            "probabilidades": self._format_probability_entries(probabilities),
            "estado": "valido",
            "stage_details": stage_details or {},
        }

    def _model_unavailable_result(self, reason):
        return {
            "clasificacion": self._display_label("en_revision"),
            "nivel_riesgo": "En revision",
            "confianza": "0.00%",
            "resumen": f"{self.metadata['summary_map']['en_revision']} Nota tecnica: {reason}",
            "recomendacion": self.metadata["recommendation_map"]["en_revision"],
            "probabilidades": [],
            "estado": "error_modelo",
            "stage_details": {},
        }

    def _blocked_result(self, probabilities, top_label, top_confidence, reason, stage_details=None):
        reason_suffix = {
            "stage1_low_confidence": " La primera etapa no pudo separar con claridad normalidad y anormalidad.",
            "stage2_low_confidence": " La segunda etapa no pudo separar con claridad VPH y cancer cervicouterino.",
            "stage1_review": " La primera etapa sugiere revision manual antes de comunicar una conclusion.",
            "stage2_review": " La segunda etapa sugiere revision manual antes de comunicar una conclusion.",
        }.get(reason, "")
        return {
            "clasificacion": self._display_label("en_revision"),
            "nivel_riesgo": "En revision",
            "confianza": f"{top_confidence * 100:.2f}%",
            "resumen": f"{self.metadata['summary_map']['en_revision']}{reason_suffix}",
            "recomendacion": self.metadata["recommendation_map"]["en_revision"],
            "probabilidades": self._format_probability_entries(probabilities),
            "estado": "bloqueado",
            "stage_details": stage_details or {},
        }

    def _predict_single_stage(self, batch):
        class_names = self.metadata.get("target_classes") or self.metadata.get("class_names", [])
        prediction = self.model.predict(batch, verbose=0)
        label, confidence, probabilities = self._decode_prediction(prediction, class_names)
        return self._format_result(label, confidence, probabilities)

    def _predict_two_stage(self, batch):
        thresholds = self.metadata.get("thresholds", {})
        stage1_class_names = self.metadata.get("stage1_class_names", ["frotis_normal", "anormal"])
        stage2_class_names = self.metadata.get("stage2_class_names", ["cancer_cervicouterino", "vph"])

        stage1_prediction = self.stage1_model.predict(batch, verbose=0)
        stage1_label, stage1_confidence, stage1_probabilities = self._decode_prediction(
            stage1_prediction,
            stage1_class_names,
        )
        stage1_margin = 0.0
        if len(stage1_probabilities) > 1:
            stage1_margin = stage1_probabilities[0]["probability"] - stage1_probabilities[1]["probability"]

        stage_details = {
            "stage1": {
                "top_class": stage1_label,
                "confidence": stage1_confidence,
                "margin": stage1_margin,
                "probabilities": stage1_probabilities,
            }
        }
        stage1_probability_map = {
            str(item["label"]).lower().strip(): float(item["probability"])
            for item in stage1_probabilities
        }
        normal_probability = stage1_probability_map.get("frotis_normal", 0.0)
        anormal_probability = stage1_probability_map.get("anormal", 0.0)

        def run_stage2():
            stage2_prediction = self.stage2_model.predict(batch, verbose=0)
            stage2_label, stage2_confidence, stage2_probabilities = self._decode_prediction(
                stage2_prediction,
                stage2_class_names,
            )
            stage2_margin = 0.0
            if len(stage2_probabilities) > 1:
                stage2_margin = stage2_probabilities[0]["probability"] - stage2_probabilities[1]["probability"]
            stage2_probability_map = {
                str(item["label"]).lower().strip(): float(item["probability"])
                for item in stage2_probabilities
            }
            stage2_details = {
                "top_class": stage2_label,
                "confidence": stage2_confidence,
                "margin": stage2_margin,
                "probabilities": stage2_probabilities,
                "probability_map": stage2_probability_map,
            }
            return (
                stage2_label,
                stage2_confidence,
                stage2_probabilities,
                stage2_margin,
                stage2_probability_map,
                stage2_details,
            )

        # Rescate de normales: si anormal gana por poco, priorizamos no sobrediagnosticar.
        if (
            stage1_label == "anormal"
            and normal_probability >= 0.30
            and (anormal_probability - normal_probability) <= 0.12
            and anormal_probability < 0.82
        ):
            return self._format_result(
                "frotis_normal",
                normal_probability,
                stage1_probabilities,
                stage_details=stage_details,
            )

        if stage1_label == "frotis_normal":
            # Red de seguridad: si Stage 1 marca normal pero no viene muy fuerte,
            # permitimos que Stage 2 corrija cuando vea lesion de forma muy clara.
            if stage1_confidence < 0.66 or stage1_margin < 0.10:
                (
                    override_label,
                    override_confidence,
                    override_probabilities,
                    override_margin,
                    override_probability_map,
                    override_details,
                ) = run_stage2()
                if (
                    (
                        override_label == "cancer_cervicouterino"
                        and override_confidence >= float(thresholds.get("stage2_cancer_override_confidence", 0.88))
                        and override_margin >= float(thresholds.get("stage2_cancer_override_margin", 0.12))
                    )
                    or (
                        override_label == "vph"
                        and override_confidence >= float(thresholds.get("stage2_vph_override_confidence", 0.97))
                        and override_margin >= float(thresholds.get("stage2_vph_override_margin", 0.28))
                        and override_probability_map.get("cancer_cervicouterino", 0.0) < 0.30
                    )
                ):
                    stage_details["stage2_override"] = override_details
                    return self._format_result(
                        override_label,
                        override_confidence,
                        override_probabilities,
                        stage_details=stage_details,
                    )

            if (
                stage1_confidence >= float(thresholds.get("stage1_normal_confidence_threshold", 0.60))
                and stage1_margin >= float(thresholds.get("stage1_min_margin", 0.04))
            ):
                return self._format_result(
                    "frotis_normal",
                    stage1_confidence,
                    stage1_probabilities,
                    stage_details=stage_details,
                )
            if stage1_confidence >= float(thresholds.get("stage1_review_threshold", 0.52)):
                return self._blocked_result(
                    stage1_probabilities,
                    stage1_label,
                    stage1_confidence,
                    "stage1_review",
                    stage_details=stage_details,
                )
            return self._blocked_result(
                stage1_probabilities,
                stage1_label,
                stage1_confidence,
                "stage1_low_confidence",
                stage_details=stage_details,
            )

        # Anormal se usa mas como compuerta que como destino final.
        # Si Stage 1 sugiere anormalidad con señal moderada, preferimos consultar Stage 2.
        if (
            stage1_confidence < float(thresholds.get("stage1_anormal_confidence_threshold", 0.58))
            or stage1_margin < 0.04
            or normal_probability >= 0.48
        ):
            return self._blocked_result(
                stage1_probabilities,
                stage1_label,
                stage1_confidence,
                "stage1_review",
                stage_details=stage_details,
            )

        (
            stage2_label,
            stage2_confidence,
            stage2_probabilities,
            stage2_margin,
            stage2_probability_map,
            stage2_details,
        ) = run_stage2()
        stage_details["stage2"] = stage2_details

        if stage2_label == "vph":
            # Regla de seguridad: si VPH gana pero CACU viene suficientemente cerca,
            # preferimos no esconder un posible cancer detras de VPH.
            if (
                stage2_probability_map.get("cancer_cervicouterino", 0.0)
                >= float(thresholds.get("stage2_cancer_from_vph_min_probability", 0.32))
                and stage2_margin <= float(thresholds.get("stage2_cancer_from_vph_max_margin", 0.18))
            ):
                return self._format_result(
                    "cancer_cervicouterino",
                    stage2_probability_map.get("cancer_cervicouterino", 0.0),
                    stage2_probabilities,
                    stage_details=stage_details,
                )
            if (
                stage2_confidence < float(thresholds.get("stage2_vph_confidence_threshold", 0.94))
                or stage2_margin < float(thresholds.get("stage2_vph_min_margin", 0.22))
                or stage2_probability_map.get("cancer_cervicouterino", 0.0) >= 0.28
            ):
                return self._blocked_result(
                    stage2_probabilities,
                    stage2_label,
                    stage2_confidence,
                    "stage2_review",
                    stage_details=stage_details,
                )
        elif stage2_label == "cancer_cervicouterino":
            if (
                stage2_confidence < float(thresholds.get("stage2_cancer_confidence_threshold", 0.80))
                or stage2_margin < float(thresholds.get("stage2_cancer_min_margin", 0.10))
            ):
                return self._blocked_result(
                    stage2_probabilities,
                    stage2_label,
                    stage2_confidence,
                    "stage2_review",
                    stage_details=stage_details,
                )

        if (
            stage2_confidence >= float(thresholds.get("stage2_confidence_threshold", 0.84))
            and stage2_margin >= float(thresholds.get("stage2_min_margin", 0.14))
        ):
            return self._format_result(
                stage2_label,
                stage2_confidence,
                stage2_probabilities,
                stage_details=stage_details,
            )
        if stage2_confidence >= float(thresholds.get("stage2_review_threshold", 0.55)):
            return self._blocked_result(
                stage2_probabilities,
                stage2_label,
                stage2_confidence,
                "stage2_review",
                stage_details=stage_details,
            )
        return self._blocked_result(
            stage2_probabilities,
            stage2_label,
            stage2_confidence,
            "stage2_low_confidence",
            stage_details=stage_details,
        )

    def predict(self, image_path, observaciones=""):
        image_path = Path(image_path)
        self._ensure_loaded()

        if self.model_bundle is None:
            return self._model_unavailable_result(self.model_error or "Modelo no disponible.")
        if (
            self.model_bundle["kind"] == "two_stage"
            and (self.stage1_model is None or self.stage2_model is None)
        ):
            return self._model_unavailable_result(self.model_error or "Modelos de dos etapas no disponibles.")
        if self.model_bundle["kind"] == "single_stage" and self.model is None:
            return self._model_unavailable_result(self.model_error or "Modelo no disponible.")

        try:
            batch = self._preprocess_image(image_path)
            if self.model_bundle["kind"] == "two_stage":
                return self._predict_two_stage(batch)
            return self._predict_single_stage(batch)
        except Exception as exc:
            self.model_error = f"La inferencia fallo: {exc}"
            LOGGER.error("La inferencia fallo para %s\n%s", image_path, traceback.format_exc())
            return self._model_unavailable_result(self.model_error)


PREDICTOR = CytologyPredictor()


def ejecutar_modelo(image_path, observaciones=""):
    return PREDICTOR.predict(image_path, observaciones)
