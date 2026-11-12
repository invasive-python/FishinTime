import argparse
import os

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the FishinTime API.")
    parser.add_argument(
        "--sandbox",
        action="store_true",
        help="Use Stripe sandbox credentials and sandbox billing records.",
    )
    args = parser.parse_args()

    os.environ["STRIPE_MODE"] = "sandbox" if args.sandbox else "live"
    uvicorn.run("api:app", reload=True)


if __name__ == "__main__":
    main()
