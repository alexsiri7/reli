
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from google.adk.models.lite_llm import LiteLlm
from google.adk.models.llm_request import LlmRequest
from google.genai import types

async def reproduce_adk_behavior():
    # Use the model that is failing in production
    model_name = "google/gemini-3-flash-preview"
    effective_model = f"openai/{model_name}"
    
    print(f"Passed to LiteLlm: {effective_model}")
    llm = LiteLlm(model=effective_model, api_base="https://router.requesty.ai/v1", api_key="fake")
    
    req = LlmRequest(
        contents=[types.Content(role="user", parts=[types.Part(text="hello")])]
    )
    
    # We want to see what reaches LiteLLM's completion
    with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "hi"
        mock_response.usage = MagicMock()
        mock_acompletion.return_value = mock_response
        
        try:
            async for _ in llm.generate_content_async(req):
                pass
        except Exception as e:
            # print(f"Caught: {e}")
            pass
            
        if mock_acompletion.called:
            kwargs = mock_acompletion.call_args.kwargs
            print(f"Reached litellm.acompletion: model={kwargs.get('model')}")
        else:
            print("litellm.acompletion was NOT called")

if __name__ == "__main__":
    asyncio.run(reproduce_adk_behavior())
