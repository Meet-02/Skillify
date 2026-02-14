from alpha_dataset import DATASET

def mean_absolute_error(true, predicted):
    return sum(abs(t - p) for t, p in zip(true, predicted)) / len(true)

def tune_alpha():
    alpha_values = [i / 100 for i in range(65, 80)]
  # 0.5 → 0.9
    best_alpha = None
    lowest_error = float("inf")

    for alpha in alpha_values:
        predicted = []

        for item in DATASET:
            final_score = (
                alpha * item["structured_score"]
                + (1 - alpha) * item["semantic_score"]
            )
            predicted.append(final_score)

        expected = [item["expected_score"] for item in DATASET]
        error = mean_absolute_error(expected, predicted)

        print(f"Alpha={alpha:.2f} | MAE={error:.2f}")

        if error < lowest_error:
            lowest_error = error
            best_alpha = alpha

    print("\n✅ Best Alpha Selected:", best_alpha)
    return best_alpha

if __name__ == "__main__":
    tune_alpha()
