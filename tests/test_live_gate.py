from copy import deepcopy
from langdock_support_lab.cli import live_pass


def test_live_gate_rejects_synthetic_missing_markers_and_failed_attempts():
    runs=[{'operation':op,'provenance':'live','status':'succeeded','observation':{'response_shape_valid':True,'probe_expectation_met':True}} for op in ('agent_completion','knowledge_search')]
    assert live_pass(runs)
    assert not live_pass([])
    for path,value in [('provenance','synthetic'),('status','failed')]:
        bad=deepcopy(runs); bad[0][path]=value
        assert not live_pass(bad)
    for field in ('response_shape_valid','probe_expectation_met'):
        bad=deepcopy(runs); bad[1]['observation'][field]=False
        assert not live_pass(bad)
