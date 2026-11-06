from app.services import bedrock


def test_sonnet_5_uses_supported_converse_parameters(monkeypatch):
    captured = {}

    class FakeClient:
        def converse(self, **kwargs):
            captured.update(kwargs)
            return {
                'output': {'message': {'content': [{'text': 'OK'}]}},
                'usage': {},
            }

    monkeypatch.setenv('BEDROCK_MODEL_ID', 'us.anthropic.claude-sonnet-5')
    monkeypatch.setattr(bedrock, 'get_bedrock_client', lambda: FakeClient())

    result = bedrock.converse_sonnet('test prompt')

    assert result['success'] is True
    assert captured['modelId'] == 'us.anthropic.claude-sonnet-5'
    assert captured['inferenceConfig'] == {'maxTokens': 4096}
