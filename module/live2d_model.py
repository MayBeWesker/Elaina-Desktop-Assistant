import json
import chardet
import re
import os
from loguru import logger

# This class will only prepare the payload for the live2d model
# the process of sending the payload should be done by the caller
# This class is **Not responsible** for sending the payload to the server


class Live2dModel:
    """
    A class to represent a Live2D model. This class only prepares and stores the information of the Live2D model. It does not send anything to the frontend or server or anything.

    Attributes:
        model_dict_path (str): The path to the model dictionary file.
        live2d_model_name (str): The name of the Live2D model.
        model_info (dict): The information of the Live2D model.
        emo_map (dict): The emotion map of the Live2D model.
        emo_str (str): The string representation of the emotion map of the Live2D model.
    """

    model_dict_path: str
    live2d_model_name: str
    model_info: dict
    emo_map: dict
    emo_str: str

    def __init__(
        self, live2d_model_name: str, model_dict_path: str | None = None
    ):

        if model_dict_path is None:
            module_dir = os.path.dirname(os.path.abspath(__file__))
            model_dict_path = os.path.join(
                os.path.dirname(module_dir), "model_dict.json"
            )
        self.model_dict_path: str = model_dict_path
        self.live2d_model_name: str = live2d_model_name
        self.set_model(live2d_model_name)

    def set_model(self, model_name: str) -> None:
        """
        Set the model with its name and load the model information. This method will initialize the `self.model_info`, `self.emo_map`, and `self.emo_str` attributes.
        This method is called in the constructor.

        Parameters:
            model_name (str): The name of the live2d model.

            Returns:
            None
        """

        self.model_info: dict = self._lookup_model_info(model_name)
        self.emo_map: dict = self.model_info["emotionMap"]
        self.emo_str: str = " ".join([f"[{key}]," for key in self.emo_map.keys()])
        # emo_str is a string of the keys in the emoMap dictionary. The keys are enclosed in square brackets.
        # example: `"[fear], [anger], [disgust], [sadness], [joy], [neutral], [surprise]"`

    def _load_file_content(self, file_path: str) -> str:
        """Load the content of a file with robust encoding handling."""
        # Try common encodings first
        encodings = ["utf-8", "utf-8-sig", "gbk", "gb2312", "ascii"]

        for encoding in encodings:
            try:
                with open(file_path, "r", encoding=encoding) as file:
                    return file.read()
            except UnicodeDecodeError:
                continue

        # If all common encodings fail, try to detect encoding
        try:
            with open(file_path, "rb") as file:
                raw_data = file.read()
            detected = chardet.detect(raw_data)
            detected_encoding = detected["encoding"]

            if detected_encoding:
                try:
                    return raw_data.decode(detected_encoding)
                except UnicodeDecodeError:
                    pass
        except Exception as e:
            logger.error(f"Error detecting encoding for {file_path}: {e}")

        raise UnicodeError(f"Failed to decode {file_path} with any encoding")

    def _lookup_model_info(self, model_name: str) -> dict:
        """
        Find the model information from the model dictionary and return the information about the matched model.

        Parameters:
            model_name (str): The name of the live2d model.

        Returns:
            dict: The dictionary with the information of the matched model.

        Raises:
            FileNotFoundError if the model dictionary file is not found.

            json.JSONDecodeError if the model dictionary file is not a valid JSON file.

            KeyError if the model name is not found in the model dictionary.

        """

        self.live2d_model_name = model_name

        try:
            file_content = self._load_file_content(self.model_dict_path)
            model_dict = json.loads(file_content)
        except FileNotFoundError as file_e:
            print(f"Model dictionary file not found at {self.model_dict_path}.")
            raise file_e
        except json.JSONDecodeError as json_e:
            print(
                f"Error decoding JSON from model dictionary file at {self.model_dict_path}."
            )
            raise json_e
        except UnicodeError as uni_e:
            print(f"Error reading model dictionary file at {self.model_dict_path}.")
            raise uni_e
        except Exception as e:
            print(
                f"Error occurred while reading model dictionary file at {self.model_dict_path}."
            )
            raise e

        # Find the model in the model_dict
        matched_model = next(
            (model for model in model_dict if model["name"] == model_name), None
        )

        if matched_model is None:
            print(f"Unable to find {model_name} in {self.model_dict_path}.")
            raise KeyError(
                f"{model_name} not found in model dictionary {self.model_dict_path}."
            )

        # The feature: "translate model url to full url if it starts with '/' " is no longer implemented here

        print("Model Information Loaded.")

        return matched_model

    def extract_emotion(self, str_to_check: str) -> list:
        """
        Check the input string for any emotion keywords and return a list of values (the expression index) of the emotions found in the string.

        Parameters:
            str_to_check (str): The string to check for emotions.

        Returns:
            list: A list of values of the emotions found in the string. An empty list is returned if no emotions are found.
        """
        
        if self.emo_map is None:
            return []

        expression_list = []
        tag_pattern = r"\[([^\[\]]+)\]|【([^【】]+)】|（([^（）]+)）|\(([^()]+)\)"
        for match in re.finditer(tag_pattern, str_to_check):
            label = next(group for group in match.groups() if group is not None)
            expression = self._emotion_index_for_label(label)
            if expression is not None:
                expression_list.append(expression)
        return expression_list

    def _emotion_index_for_label(self, label: str) -> int | None:
        """Resolve official English tags and common Chinese stage directions."""
        normalized = label.strip().lower()
        normalized = re.sub(r"^(语气|表情)[:：]?", "", normalized)
        normalized = re.sub(r"(地|的语气|表情)$", "", normalized)

        aliases = {
            "开心": "joy", "高兴": "joy", "喜悦": "joy", "微笑": "joy",
            "兴奋": "excitement", "惊喜": "surprise", "惊讶": "surprise",
            "伤心": "sad", "难过": "sad", "悲伤": "sad",
            "担心": "worry", "忧虑": "worry", "生气": "anger",
            "愤怒": "anger", "厌恶": "disgust", "害羞": "shy",
            "羞涩": "shy", "思考": "confusion", "困惑": "confusion",
            "疑惑": "confusion", "期待": "expectation", "平静": "neutral",
            "自然": "neutral", "中性": "neutral", "温柔": "shy",
        }
        key = aliases.get(normalized, normalized)
        return self.emo_map.get(key)

    def remove_emotion_keywords(self, target_str: str) -> str:
        """
        Remove the emotion keywords from the input string and return the cleaned string.

        Parameters:
            str_to_check (str): The string to check for emotions.

        Returns:
            str: The cleaned string with the emotion keywords removed.
        """

        if self.emo_map is None:
            return target_str

        tag_pattern = r"\[([^\[\]]+)\]|【([^【】]+)】|（([^（）]+)）|\(([^()]+)\)"

        def remove_if_emotion(match: re.Match) -> str:
            label = next(group for group in match.groups() if group is not None)
            return "" if self._emotion_index_for_label(label) is not None else match.group(0)

        return re.sub(tag_pattern, remove_if_emotion, target_str)


if __name__ == "__main__":
    live2d_model = Live2dModel("shizuku-local")
    print(live2d_model.model_info)
    print(live2d_model.emo_map)
    print(live2d_model.emo_str)
    test_str = "[*joins hands and smi]les* * [SmIrK]: HEHE, YOU THINK YOU CAN HANDLE THE TRUTH?[anger][anger] [anger] [smirk] [anger]["
    print(test_str)
    print(live2d_model.extract_emotion(test_str))
    print(live2d_model.remove_emotion_keywords(test_str))
