from typing import Dict, Any
from core.answer_key import answer_variants, normalize_answer

class ScoringService:
    def __init__(self, answer_key: Dict[str, str]):
        """
        :param answer_key: Словарь {"1": "15", "2": "-7", ...}
        """
        self.answer_key = answer_key

    def score(self, answers_final: Dict[str, str]) -> Dict[str, Any]:
        matched_keys = {}
        correct_count = 0
        
        for task, correct_ans in self.answer_key.items():
            student_ans = answers_final.get(task, "")
            student_norm = normalize_answer(student_ans)
            variants = answer_variants(correct_ans)
            
            is_correct = student_norm in variants
            if is_correct:
                correct_count += 1
                
            matched_keys[task] = {
                "student": student_ans,
                "student_normalized": student_norm,
                "correct": correct_ans,
                "correct_variants": variants,
                "is_correct": is_correct
            }
            
        return {
            "correct_count": correct_count,
            "total_tasks": len(self.answer_key),
            "matched_keys": matched_keys
        }
