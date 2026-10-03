# tests/test_catalog.py

# test /v1/models-catalog endpoint


"""
Test if get /v1/models-catalog
returns every seeded-model with correct provider,
and tier name.

models table in sk_test:

id |       model_id        | provider  |     display_name      | min_tier_id | context_window | is_active |         created_on         | input_price_per_1M | output_price_per_1M |   max_token_schema    | context_budget_tokens 
----+-----------------------+-----------+-----------------------+-------------+----------------+-----------+----------------------------+--------------------+---------------------+-----------------------+-----------------------
  1 | gpt-5.6-sol           | openai    | GPT-5.6 Sol           |           1 |        1050000 | t         | 2026-10-03 09:28:05.730305 |           4.000000 |           20.000000 | max_completion_tokens |                100000
  2 | google/gemini-3.1-pro | google    | GEMINI-3.1 PRO        |           1 |        1048576 | t         | 2026-10-03 09:28:05.736755 |           4.000000 |           18.000000 | max_output_tokens     |                100000
  3 | claude-opus-5         | anthropic | CLAUDE OPUS-5         |           1 |        1000000 | t         | 2026-10-03 09:28:05.739235 |           5.000000 |           25.000000 | max_tokens            |                100000
  4 | gemini-3.5-flash      | google    | GEMINI-3 FLASH        |           2 |        1048576 | t         | 2026-10-03 09:28:05.741804 |           1.500000 |            9.000000 | max_output_tokens     |                100000
  5 | gpt-5.6-terra         | openai    | GPT-5.6 TERRA         |           2 |         200000 | t         | 2026-10-03 09:28:05.744691 |           2.000000 |           12.000000 | max_completion_tokens |                100000
  6 | claude-sonnet-5       | anthropic | CLAUDE SONNET-5       |           2 |        1000000 | t         | 2026-10-03 09:28:05.747237 |           1.000000 |            5.000000 | max_tokens            |                100000
  7 | gpt-5.6-luna          | openai    | GPT-5.6 LUNA          |           3 |        1000000 | t         | 2026-10-03 09:28:05.750925 |           0.200000 |            1.200000 | max_completion_tokens |                100000
  8 | gemini-3.5-flash-lite | google    | GEMINI 3.5 FLASH LITE |           3 |        1000000 | t         | 2026-10-03 09:28:05.754119 |           0.250000 |            1.500000 | max_output_tokens     |                100000
  9 | claude-haiku-4.5      | anthropic | CLAUDE HAIKU 4.5      |           3 |        1000000 | t         | 2026-10-03 09:28:05.756757 |           1.000000 |            4.000000 | max_tokens            |                100000

"""
async def test_models_catalog_returns_all_seeded_models_with_exact_provider_names_and_tier_id(client):
    response = await client.get('v1/models-catalog') 
    # assert is request went through succesfully
    assert response.status_code == 200    

    body = []
    for r_json in response.json():
        body.append(r_json)
    # assert if first response is gpt-5.6-sol
    assert body[0]['model_name'] == 'gpt-5.6-sol'
    assert body[0]['provider'] == 'openai'
    assert body[0]['tier'] == 'Premium'
    # assery google/gemini-3.1-pro
    assert body[1]['model_name'] == 'google/gemini-3.1-pro'
    assert body[1]['provider'] == 'google'
    assert body[1]['tier'] == 'Premium'
    # assert claude-opus-5
    assert body[2]['model_name'] == 'claude-opus-5'
    assert body[2]['provider'] == 'anthropic'
    assert body[2]['tier'] == 'Premium'
    # assert gemini-3.5-flash
    assert body[3]['model_name'] == 'gemini-3.5-flash'
    assert body[3]['provider'] == 'google'
    assert body[3]['tier'] == 'Pro'
    # assert gpt-5.6-terra
    assert body[4]['model_name'] == 'gpt-5.6-terra'
    assert body[4]['provider'] == 'openai'
    assert body[4]['tier'] == 'Pro'
    # assert claude-sonnet-5
    assert body[5]['model_name'] == 'claude-sonnet-5'
    assert body[5]['provider'] == 'anthropic'
    assert body[5]['tier'] == 'Pro'
    # assert gpt-5.6-luna
    assert body[6]['model_name'] == 'gpt-5.6-luna'
    assert body[6]['provider'] == 'openai'
    assert body[6]['tier'] == 'Basic'
    # assert gemini-3.5-flash-lite
    assert body[7]['model_name'] == 'gemini-3.5-flash-lite'
    assert body[7]['provider'] == 'google'
    assert body[7]['tier'] == 'Basic'
    #assert claude-haiku-4.5
    assert body[8]['model_name'] == 'claude-haiku-4.5'
    assert body[8]['provider'] == 'anthropic'
    assert body[8]['tier'] == 'Basic'












   














        
