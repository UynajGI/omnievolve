"""全功能自主探索 debug — 逐子系统验证."""
import sys, traceback, tempfile, os
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'

PASS = 0
FAIL = 0
ERRORS = []

def check(name, fn):
    global PASS, FAIL
    try:
        result = fn()
        PASS += 1
        print(f"  ✓ {name}: {result}")
    except Exception as e:
        FAIL += 1
        ERRORS.append((name, str(e)[:120]))
        print(f"  ✗ {name}: {e}")

# ═══════════════════════════════════════════
print("\n═══ 1. Storage Layer ═══")
# ═══════════════════════════════════════════

def t_db():
    from omnievolve.storage.db import create_memory_database, Database
    db = create_memory_database()
    from omnievolve.storage.migrations import initialize_database
    initialize_database(db)
    tables = db.fetchall("SELECT name FROM sqlite_master WHERE type='table'")
    db.close()
    return f"{len(tables)} tables"
check("Database + migrations", t_db)

def t_artifact_store():
    from omnievolve.storage.artifact_store import ArtifactStore
    from omnievolve.storage.db import create_memory_database
    from omnievolve.storage.migrations import initialize_database
    db = create_memory_database(); initialize_database(db)
    store = ArtifactStore(tempfile.mkdtemp(), db)
    h = store.store_text("hello world", "source")
    loaded = store.load_text(h)
    assert loaded == "hello world"
    assert store.exists(h)
    db.close()
    return f"store/load/exists OK, hash={h[:10]}"
check("ArtifactStore CAS", t_artifact_store)

def t_graph_store():
    from omnievolve.storage.graph_store import GraphStore
    from omnievolve.storage.db import create_memory_database
    from omnievolve.storage.migrations import initialize_database
    db = create_memory_database(); initialize_database(db)
    gs = GraphStore(db)
    # FK 数据准备
    db.execute("INSERT OR IGNORE INTO embedding_profile (id, purpose, provider, model, dimension, collection_path) VALUES ('p1', 'code', 'local', 'test', 128, '/tmp/t')")
    db.execute("INSERT INTO experiment (id, task_id, task_name, config_snapshot) VALUES ('e1', 't', 't', '{}')")
    db.execute("INSERT OR IGNORE INTO artifact (hash, artifact_type, byte_size, relative_path) VALUES ('h1', 'source', 10, 'a/h/1')")
    db.execute("INSERT OR IGNORE INTO task_evaluator_version (id, name, semantic_version, implementation_hash, task_semantics_hash, score_schema) VALUES ('ev1', 'test', '1.0', 'h', 'h', '{}')")
    db.execute("INSERT OR IGNORE INTO execution_environment_version (id, backend, resource_policy, network_policy) VALUES ('env1', 'subprocess', '{}', '{}')")
    db.execute("INSERT OR IGNORE INTO search_policy_version (id, experiment_id, version, genome, risk_level, status, artifact_hash) VALUES ('sp1', 'e1', 1, '{}', 'L0', 'champion', 'h1')")
    cid = gs.add_candidate({"id": "c1", "experiment_id": "e1", "artifact_hash": "h1", "generation": 1, "island_id": "i0", "search_policy_id": "sp1"}, [])
    assert cid == "c1"
    db.close()
    return "add_candidate OK"
check("GraphStore write methods", t_graph_store)

def t_vector_backend():
    from omnievolve.storage.zvec_backend import create_vector_backend
    from omnievolve.storage.vector_backend import VectorRecord
    import numpy as np
    b = create_vector_backend(prefer_zvec=True)
    b.create_or_open("test_coll", dimension=8)
    vecs = [np.random.randn(8).tolist() for _ in range(5)]
    records = [VectorRecord(id=f"id_{i}", vector=v, metadata={}) for i, v in enumerate(vecs)]
    b.upsert("test_coll", records)
    hits = b.query("test_coll", vecs[0], top_k=3)
    assert len(hits) >= 1
    return f"backend={type(b).__name__}, query={len(hits)} hits"
check("VectorBackend (zvec/numpy)", t_vector_backend)

def t_vector_store():
    from omnievolve.storage.vector_store import VectorStore
    from omnievolve.storage.zvec_backend import create_vector_backend
    from omnievolve.utils.embedding import FakeEmbedder
    backend = create_vector_backend(prefer_zvec=False)
    embedder = FakeEmbedder(dimension=128)
    vs = VectorStore(backend, embedder)
    is_novel, sim = vs.check_novelty("test code", collection="test_novel")
    return f"check_novelty: novel={is_novel}, sim={sim:.2f}"
check("VectorStore facade", t_vector_store)

def t_job_store():
    from omnievolve.storage.job_store import JobStore
    from omnievolve.storage.db import create_memory_database
    from omnievolve.storage.migrations import initialize_database
    db = create_memory_database(); initialize_database(db)
    db.execute("INSERT INTO experiment (id, task_id, task_name, config_snapshot) VALUES ('e1', 't', 't', '{}')")
    js = JobStore(db)
    job = js.create_job(experiment_id="e1", job_type="test", payload={"k": "v"})
    claimed = js.claim_job_by_id(job.id)
    assert claimed is not None
    js.complete_job(job.id, result_ref="ref123")
    db.close()
    return "create→claim→complete OK"
check("JobStore lifecycle", t_job_store)

def t_uow():
    from omnievolve.storage.uow import UnitOfWork
    from omnievolve.storage.db import create_memory_database
    from omnievolve.storage.migrations import initialize_database
    db = create_memory_database(); initialize_database(db)
    uow = UnitOfWork(db)
    uow.begin()
    uow.connection.execute("SELECT 1")
    uow.commit()
    db.close()
    return "begin/commit OK"
check("UnitOfWork", t_uow)

def t_async_db():
    import asyncio
    from omnievolve.storage.async_db import AsyncDatabase
    from omnievolve.storage.db import create_memory_database
    from omnievolve.storage.migrations import initialize_database
    db = create_memory_database(); initialize_database(db)
    adb = AsyncDatabase(db)
    async def run():
        r = await adb.fetchone_async("SELECT 1 as v")
        return r["v"]
    v = asyncio.run(run())
    db.close()
    return f"async query={v}"
check("AsyncDatabase", t_async_db)

# ═══════════════════════════════════════════
print("\n═══ 2. Git CodeStore ═══")
# ═══════════════════════════════════════════

def t_git_store():
    from omnievolve.storage.git_code_store import GitCodeStore
    tmpdir = tempfile.mkdtemp()
    store = GitCodeStore(f"{tmpdir}/repos", f"{tmpdir}/wts")
    store.bind_experiment("exp1", task_name="test_task")
    ref = store.store_snapshot("def f(): return 1", message="test")
    code = store.load_snapshot(ref)
    assert "def f" in code
    ws = store.materialize(ref)
    assert (ws.path / "main.py").exists()
    store.release(ws)
    return f"store/load/materialize/release OK, sha={ref[:10]}"
check("GitCodeStore full lifecycle", t_git_store)

def t_cas_store():
    from omnievolve.storage.cas_code_store import CASCodeStore
    from omnievolve.storage.artifact_store import ArtifactStore
    from omnievolve.storage.db import create_memory_database
    from omnievolve.storage.migrations import initialize_database
    from pathlib import Path
    db = create_memory_database(); initialize_database(db)
    art = ArtifactStore(tempfile.mkdtemp(), db)
    cas = CASCodeStore(art, Path(tempfile.mkdtemp()))
    ref = cas.store_snapshot("def g(): return 2", message="cas test")
    code = cas.load_snapshot(ref)
    assert "def g" in code
    ws = cas.materialize(ref)
    assert (ws.path / "main.py").exists()
    cas.release(ws)
    db.close()
    return f"CAS adapter OK, hash={ref[:10]}"
check("CASCodeStore adapter", t_cas_store)

def t_code_store_factory():
    from omnievolve.storage.code_store import create_code_store, CodeStore
    from omnievolve.config import StorageSettings
    from omnievolve.storage.db import create_memory_database
    from omnievolve.storage.migrations import initialize_database
    db = create_memory_database(); initialize_database(db)
    s1 = create_code_store(StorageSettings(code_backend="git", git_repo_path=tempfile.mkdtemp(), git_worktree_dir=tempfile.mkdtemp()), db)
    assert isinstance(s1, CodeStore) and s1.backend_name == "git"
    s2 = create_code_store(StorageSettings(code_backend="cas", artifact_dir=tempfile.mkdtemp()), db)
    assert isinstance(s2, CodeStore) and s2.backend_name == "cas"
    db.close()
    return "factory: git + cas both OK"
check("CodeStore factory", t_code_store_factory)

# ═══════════════════════════════════════════
print("\n═══ 3. Engine Core ═══")
# ═══════════════════════════════════════════

def t_mcts():
    from omnievolve.engine.mcts import ProgressiveMCGS
    mcts = ProgressiveMCGS()
    mcts.add_node("root", parent=None)
    mcts.add_node("child1", parent="root")
    mcts.add_node("child2", parent="root")
    selected = mcts.select("root")
    assert selected in ("child1", "child2")
    mcts.backpropagate(selected, 0.8)
    mcts.rollback_last_select()
    return f"select={selected}, backprop+rollback OK"
check("MCTS select/backprop/rollback", t_mcts)

def t_selection():
    from omnievolve.engine.selection import ParentSelector
    from omnievolve.storage.db import create_memory_database
    from omnievolve.storage.migrations import initialize_database
    db = create_memory_database(); initialize_database(db)
    ps = ParentSelector(db, strategy="tournament")
    result = ps.select("e1", "v1", "env1")
    db.close()
    return f"strategy=tournament, select={result}"
check("ParentSelector", t_selection)

def t_novelty():
    from omnievolve.engine.novelty import NoveltyGate, compute_code_signature
    sig = compute_code_signature("def f(): return 1")
    assert isinstance(sig, str) and len(sig) > 0
    gate = NoveltyGate()
    result = gate.check("optimize sort", existing_similarities=[0.3])
    return f"signature={sig[:10]}, novelty={result.decision}"
check("NoveltyGate + AST signature", t_novelty)

def t_memory():
    from omnievolve.engine.memory import MemoryStore
    from omnievolve.storage.db import create_memory_database
    from omnievolve.storage.migrations import initialize_database
    db = create_memory_database(); initialize_database(db)
    ms = MemoryStore(db)
    rec = ms.add_memory(scope_level=1, outcome_summary={"result": "worked"}, success_flag=True)
    results = ms.retrieve(scope_levels=[1], limit=3)
    db.close()
    return f"add+retrieve OK, id={rec.id[:8]}, results={len(results)}"
check("MemoryStore L0-L4", t_memory)

def t_island():
    from omnievolve.engine.island import IslandManager
    im = IslandManager(num_islands=4)
    should = im.should_migrate(current_gen=5)
    return f"4 islands, should_migrate(gen=5)={should}"
check("IslandManager", t_island)

def t_crossover():
    from omnievolve.engine.crossover import CrossoverOperator
    co = CrossoverOperator()
    result = co.combine(["def a(): return 1", "def b(): return 2"], strategy="segment")
    assert isinstance(result, str) and len(result) > 0
    return f"segment crossover: {len(result)} chars"
check("CrossoverOperator", t_crossover)

def t_diff():
    from omnievolve.engine.diff import parse_diffs, apply_diffs
    diff_text = "<<<<<<< SEARCH\ndef f(): return 1\n=======\ndef f(): return 2\n>>>>>>> REPLACE"
    diffs = parse_diffs(diff_text)
    result = apply_diffs("def f(): return 1\n", diffs)
    assert result is not None and "return 2" in result
    return f"parse+apply OK, {len(diffs)} diffs"
check("Diff parse/apply", t_diff)

def t_epiplexity():
    from omnievolve.engine.epiplexity import EpiplexityEstimator
    est = EpiplexityEstimator()
    score = est.score("def f():\n    return sorted(arr)")
    assert 0 <= score <= 1
    return f"epiplexity score={score:.3f}"
check("EpiplexityEstimator", t_epiplexity)

def t_checkpoint():
    from omnievolve.engine.checkpoint import CheckpointManager
    from omnievolve.storage.db import create_memory_database
    from omnievolve.storage.migrations import initialize_database
    db = create_memory_database(); initialize_database(db)
    cm = CheckpointManager(db)
    cm.save(experiment_id="e1", generation=5, total_candidates=20, meta_scratchpad="test", failed_directions=[], recent_scores=[0.5])
    loaded = cm.load("e1")
    db.close()
    return f"save+load OK, loaded={loaded is not None}"
check("CheckpointManager", t_checkpoint)

# ═══════════════════════════════════════════
print("\n═══ 4. Agents ═══")
# ═══════════════════════════════════════════

def t_router():
    from omnievolve.agents.router import ModelRouter, ModelSlot, RouteContext
    slots = [
        ModelSlot(name="heavy", tier="heavy", cost_per_1k_input=0.01, cost_per_1k_output=0.03, avg_latency_ms=500),
        ModelSlot(name="light", tier="light", cost_per_1k_input=0.001, cost_per_1k_output=0.003, avg_latency_ms=100),
    ]
    router = ModelRouter(slots)
    ctx = RouteContext(role="coder", generation=1, stagnation_level=0.0, novelty_deficit=0.0, implementation_difficulty=0.0, remaining_token_ratio=1.0, remaining_compute_ratio=1.0)
    slot_name = router.select(ctx)
    return f"selected={slot_name}"
check("ModelRouter UCB", t_router)

def t_fusion():
    from omnievolve.agents.fusion import FusionAgent
    from unittest.mock import MagicMock
    llm = MagicMock()
    llm.chat.return_value = MagicMock(content="```python\ndef f(): return 1\n```")
    f = FusionAgent(llm)
    result = f.fuse("def a(): return 1", [{"code": "def b(): return 2", "score": 0.5}])
    return f"fuse result: {type(result).__name__}"
check("FusionAgent", t_fusion)

def t_data_leakage():
    from omnievolve.agents.data_leakage import DataLeakageDetector
    d = DataLeakageDetector()
    r = d.check("x = sorted(arr)", "", 0.6, 0.5)
    assert r.has_leakage is False
    return f"no leakage, confidence={r.confidence}"
check("DataLeakageDetector", t_data_leakage)

def t_circuit_breaker():
    from omnievolve.agents.circuit_breaker import CircuitBreaker
    cb = CircuitBreaker(failure_threshold=3, reset_timeout_sec=1.0)
    state = cb.state
    return f"state={state}"
check("CircuitBreaker", t_circuit_breaker)

def t_headless():
    from omnievolve.agents.headless_provider import parse_headless_model, _build_command
    hm = parse_headless_model("headless/claude-code@sonnet?effort=high")
    cmd = _build_command(hm)
    return f"agent={hm.agent}, model={hm.model}, cmd={cmd}"
check("HeadlessProvider", t_headless)

# ═══════════════════════════════════════════
print("\n═══ 5. Eval Layer ═══")
# ═══════════════════════════════════════════

def t_self_evaluator():
    from omnievolve.eval.self_evaluator import SelfEvaluator
    from omnievolve.eval.telemetry import TelemetryAggregator
    from omnievolve.eval.health_policy import HealthPolicy
    from omnievolve.storage.db import create_memory_database
    from omnievolve.storage.migrations import initialize_database
    db = create_memory_database(); initialize_database(db)
    ta = TelemetryAggregator(db)
    hp = HealthPolicy()
    se = SelfEvaluator(ta, hp)
    db.close()
    return "init OK"
check("SelfEvaluator", t_self_evaluator)

def t_telemetry():
    from omnievolve.eval.telemetry import TelemetryAggregator
    from omnievolve.storage.db import create_memory_database
    from omnievolve.storage.migrations import initialize_database
    db = create_memory_database(); initialize_database(db)
    ta = TelemetryAggregator(db)
    db.close()
    return "init OK"
check("TelemetryAggregator", t_telemetry)

def t_health_policy():
    from omnievolve.eval.health_policy import HealthPolicy
    hp = HealthPolicy()
    return "init OK"
check("HealthPolicy", t_health_policy)

def t_metrics():
    from omnievolve.eval.metrics import MetricsCalculator
    mc = MetricsCalculator()
    roi = mc.compute_roi(frontier_improvement=0.1, api_cost_usd=0.01, compute_cost_sec=10.0, wall_time_sec=60.0)
    return f"ROI={roi:.3f}"
check("Metrics (ROI)", t_metrics)

def t_early_stop():
    from omnievolve.eval.early_stop import BayesianEarlyStop
    es = BayesianEarlyStop(prob_cutoff=0.95, min_trials=3)
    decision = es.check([0.5, 0.5, 0.5, 0.5], threshold=0.6)
    return f"check result={decision}"
check("EarlyStopper", t_early_stop)

# ═══════════════════════════════════════════
print("\n═══ 6. Meta (Slow Loop) ═══")
# ═══════════════════════════════════════════

def t_governance():
    from omnievolve.meta.governance import GovernancePolicy, MetaAction, RiskLevel
    gp = GovernancePolicy()
    action = MetaAction(action_type="modify_field", target="mutation_rate", old_value=0.2, new_value=0.3, risk_level=RiskLevel.L0)
    can, reason = gp.can_apply(action)
    return f"can_apply={can}, reason={reason}"
check("GovernancePolicy L0/L1/L2", t_governance)

def t_policy_genome():
    from omnievolve.meta.policy_genome import SearchPolicyGenome
    g = SearchPolicyGenome()
    d = g.to_dict()
    g2 = SearchPolicyGenome.from_dict(d)
    return f"genome fields: {list(d.keys())[:5]}"
check("SearchPolicyGenome", t_policy_genome)

def t_policy_archive():
    from omnievolve.meta.policy_archive import PolicyArchive
    from omnievolve.storage.db import create_memory_database
    from omnievolve.storage.migrations import initialize_database
    db = create_memory_database(); initialize_database(db)
    db.execute("INSERT INTO experiment (id, task_id, task_name, config_snapshot) VALUES ('e1', 't', 't', '{}')")
    pa = PolicyArchive(db)
    from omnievolve.meta.policy_genome import SearchPolicyGenome
    p = pa.create_policy(SearchPolicyGenome(), experiment_id="e1", parent_policy_id=None, risk_level="L0")
    db.close()
    return f"create_policy OK, id={p.id[:8]}"
check("PolicyArchive", t_policy_archive)

def t_prompt_evolver():
    from omnievolve.meta.prompt_evolver import PromptEvolver
    import random
    random.seed(42)
    pe = PromptEvolver(mutation_rate=1.0)
    new_prompt, mutations = pe.evolve("You are a coder.")
    return f"mutations={len(mutations)}, changed={new_prompt != 'You are a coder.'}"
check("PromptEvolver", t_prompt_evolver)

def t_hyperparam_tuner():
    from omnievolve.meta.hyperparam_tuner import BayesianTuner, ParamSpec
    bt = BayesianTuner(param_space=[ParamSpec(name="mutation_rate", kind="float", low=0.1, high=0.9)])
    suggestion = bt.suggest()
    bt.update(suggestion, score=0.5)
    return f"suggest={suggestion}, best={bt.get_best().score}"
check("BayesianTuner", t_hyperparam_tuner)

def t_replay():
    from omnievolve.meta.replay_evaluator import ReplayEvaluator
    re = ReplayEvaluator(budget_ratio=0.1)
    decision = re.compare(champion_scores=[0.5, 0.6], challenger_scores=[0.7])
    return f"decision={decision.get('decision')}"
check("ReplayEvaluator", t_replay)

def t_meta_scratchpad():
    from omnievolve.meta.meta_scratchpad import MetaScratchpad
    from unittest.mock import MagicMock
    llm = MagicMock()
    llm.chat.return_value = MagicMock(content='{"insights": ["test"], "recommendations": ["try x"]}')
    ms = MetaScratchpad(llm=llm)
    result = ms.run(candidates=[{"id": "c1", "score": 0.5}])
    return f"run OK, type={type(result).__name__}"
check("MetaScratchpad", t_meta_scratchpad)

# ═══════════════════════════════════════════
print("\n═══ 7. Sandbox + Plugins ═══")
# ═══════════════════════════════════════════

def t_subprocess_backend():
    from omnievolve.sandbox.subprocess_backend import TrustedSubprocessBackend
    sb = TrustedSubprocessBackend(trusted=True)
    return f"init OK, type={type(sb).__name__}"
check("TrustedSubprocessBackend", t_subprocess_backend)

def t_sandbox_registry():
    from omnievolve.sandbox.registry import create_backend
    sb = create_backend("trusted_subprocess", trusted=True)
    return f"create_backend('trusted_subprocess')={type(sb).__name__}"
check("Sandbox registry", t_sandbox_registry)

def t_plugin_discovery():
    from omnievolve.plugins.discovery import discover_plugins, _REGISTERED_PLUGINS
    plugins = discover_plugins()
    return f"discovered={len(plugins)}, registered={len(_REGISTERED_PLUGINS)}"
check("Plugin discovery", t_plugin_discovery)

# ═══════════════════════════════════════════
print("\n═══ 8. Utils ═══")
# ═══════════════════════════════════════════

def t_embedding():
    from omnievolve.utils.embedding import FakeEmbedder
    e = FakeEmbedder(dimension=128)
    v = e.embed(["hello", "world"])
    assert len(v) == 2 and len(v[0]) == 128
    return f"dim=128, batch={len(v)}"
check("FakeEmbedder", t_embedding)

def t_profiling():
    from omnievolve.utils.profiling import PipelineProfiler, StepTimer
    with StepTimer("test_step"):
        pass
    return "StepTimer OK"
check("Profiling (StepTimer)", t_profiling)

def t_response():
    from omnievolve.utils.response import extract_jsons, extract_code
    jsons = extract_jsons('{"thought": "test", "nested": {"a": 1}}')
    assert len(jsons) >= 1
    code = extract_code("```python\ndef f(): pass\n```")
    assert len(code) >= 1
    return f"jsons={len(jsons)}, code_blocks={len(code)}"
check("Response parsing (JSON+code)", t_response)

def t_complexity():
    from omnievolve.utils.complexity import analyze_code_metrics
    m = analyze_code_metrics("def f():\n    if True:\n        return 1\n    return 0")
    return f"CC={m['cyclomatic_complexity']}, nesting={m['nesting_depth']}"
check("Code complexity metrics", t_complexity)

def t_safe_json():
    from omnievolve.utils import safe_json_loads
    r1 = safe_json_loads('{"a": 1}', default={})
    r2 = safe_json_loads('invalid json', default={"fallback": True})
    r3 = safe_json_loads(None, default=[])
    assert r1 == {"a": 1} and r2 == {"fallback": True} and r3 == []
    return "valid/invalid/None all handled"
check("safe_json_loads", t_safe_json)

# ═══════════════════════════════════════════
print("\n═══ 9. Config + Async ═══")
# ═══════════════════════════════════════════

def t_config():
    from omnievolve.config import load_settings
    s = load_settings(None)
    assert s.evolution.max_generations > 0
    assert s.storage.code_backend in ("cas", "git")
    return f"gens={s.evolution.max_generations}, backend={s.storage.code_backend}"
check("Config loading", t_config)

def t_async_pipeline():
    from omnievolve.engine.async_engine import AsyncPipelineEngine
    from unittest.mock import MagicMock
    engine = MagicMock()
    engine._config = MagicMock()
    engine._config.population_size = 4
    engine._config.max_generations = 2
    engine._config.island_count = 1
    engine._config.health_window_gens = 3
    engine._config.self_evolve_enabled = False
    engine._budget_guard = MagicMock()
    engine._budget_guard.state.is_exhausted = False
    engine._best_candidate = None
    engine._current_generation = 0
    pipeline = AsyncPipelineEngine(engine)
    pipeline._update_ewma("sampling", 1.0)
    pipeline._update_ewma("commit", 2.0)
    target = pipeline._compute_pipeline_target()
    return f"ewma_s={pipeline._sampling_ewma:.1f}, ewma_c={pipeline._eval_ewma:.1f}, target={target}"
check("AsyncPipelineEngine EWMA", t_async_pipeline)

# ═══════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════
print(f"\n{'='*50}")
print(f"RESULTS: {PASS} passed, {FAIL} failed")
if ERRORS:
    print(f"\nFailed checks:")
    for name, err in ERRORS:
        print(f"  ✗ {name}: {err}")
print(f"{'='*50}")
