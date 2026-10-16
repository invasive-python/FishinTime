# fishin_time

## OpenAI agent setup

Install the project dependencies with `pip install -r requirements.txt`. Put
your OpenAI API key in the project-root `.env` file:

```text
OPENAI_API_KEY=your-api-key
```

The forecast endpoint loads this value to call the configured OpenAI agent.
Keep `.env` private; it is excluded from Git.
