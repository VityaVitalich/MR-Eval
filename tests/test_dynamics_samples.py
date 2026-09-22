"""Question-level data contracts for the Dynamics bootstrap and EM filtering."""
import json

import pytest

import build_data as b


def test_em_samples_keep_question_ids_and_missing_scores(tmp_path):
    path = tmp_path / 'em.json'
    path.write_text(json.dumps({'results': [
        {'question_id': 'q1', 'aligned': 0, 'coherent': 90},
        {'question_id': 'q1', 'aligned': 100, 'coherent': 20},
        {'question_id': 'q2', 'aligned': None, 'coherent': 80},
    ]}))
    cell = b._em_cell_from_path(path, 'test')
    assert cell['test_samples'] == [['q1', 0, 90], ['q1', 100, 20], ['q2', None, 80]]
    assert cell['aligned_mean'] == 50


def test_lazy_samples_preserve_questions_and_step_alignment(tmp_path):
    samples = [[['q1', 0, 90], ['q1', 100, 40]], None]
    data = {'models': {'model': {'dynamics': {'rl_em': {
        'iterations': [0, 100], 'aligned_mean': [50, None],
        'test_samples': {'format': 'em', 'steps': samples},
    }}}}}
    b.emit_dynamics_test_samples(data, tmp_path)
    payload = json.loads((tmp_path / 'dynamics/model_rl_em.json').read_text())
    assert payload['default']['steps'] == samples
    assert payload['default']['iterations'] == [0, 100]
    sub = data['models']['model']['dynamics']['rl_em']
    assert 'test_samples' not in sub
    assert sub['test_samples_key'] == 'default'
    assert sub['test_samples_file'] == 'diagnostics/dynamics/model_rl_em.json'


def test_lazy_samples_mismatched_steps_fail(tmp_path):
    data = {'models': {'m': {'dynamics': {'rl_em': {
        'iterations': [0, 100], 'test_samples': {'format': 'em', 'steps': [[]]}
    }}}}}
    with pytest.raises(ValueError, match='mismatch'):
        b.emit_dynamics_test_samples(data, tmp_path)


def test_diagnostics_cleanup_preserves_dynamics_samples(tmp_path, monkeypatch):
    monkeypatch.setattr(b, 'PQ_PRETRAIN_FILE', tmp_path / 'absent-pretrain.json')
    dest = tmp_path / 'dynamics'
    dest.mkdir()
    sample = dest / 'model_em.json'
    sample.write_text('{"default": {"steps": []}}')
    b.build_diagnostics(set(), tmp_path, models={})
    assert sample.exists()
