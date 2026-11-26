def test_slurm_module_still_importable():
    """Test old slurm module still importable"""
    import valska.external_tools.bayeseor.slurm

    assert valska.external_tools.bayeseor.slurm is not None
