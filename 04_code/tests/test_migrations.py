"""Tests migrations Alembic (revue adversariale + validation Postgres 2026-07-07).

Couvre deux findings :
  1. IDs de révision ≤ 32 caractères : alembic_version.version_num est un VARCHAR(32)
     par défaut sur Postgres — un ID plus long fait échouer `alembic upgrade head` sur
     base VIERGE (StringDataRightTruncation) et rollback TOUTE la chaîne. Invisible
     sur SQLite (longueurs VARCHAR non appliquées) : d'où ce garde-fou statique.
  2. Migration 0015 (uq_response_session_item) : les bases ayant tourné avec la garde
     non atomique peuvent contenir des doublons (session_id, item_id) — la migration
     doit les DÉDOUBLONNER (en gardant la plus ancienne réponse) AVANT d'ajouter la
     contrainte, sinon elle bloque le déploiement du correctif lui-même.
"""
import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[1]


def _alembic_cfg() -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    return cfg


def test_revision_ids_max_32_chars():
    # Garde-fou Postgres : tout ID > 32 chars casse l'UPDATE d'alembic_version.
    script = ScriptDirectory.from_config(_alembic_cfg())
    for rev in script.walk_revisions():
        assert len(rev.revision) <= 32, (
            f"revision {rev.revision!r} fait {len(rev.revision)} caractères "
            f"(> VARCHAR(32) d'alembic_version sur Postgres)"
        )


def test_exactement_un_head():
    # Une chaîne fourchue (2 heads) rend `alembic upgrade head` ambigu → déploiement cassé.
    heads = ScriptDirectory.from_config(_alembic_cfg()).get_heads()
    assert len(heads) == 1, f"chaîne Alembic fourchue : {heads!r}"


def _hex(u: uuid.UUID) -> str:
    """sa.Uuid stocke l'UUID en hex 32 chars (sans tirets) sur SQLite."""
    return u.hex


def _insert_response(conn, *, rid, session_id, item_id, created_at,
                     school_id, student_id, competency_id):
    conn.execute(sa.text(
        "INSERT INTO response (id, school_id, student_id, item_id, competency_id, "
        "is_correct, response_time_ms, session_id, created_at) "
        "VALUES (:id, :school, :student, :item, :comp, 1, NULL, :session, :created)"
    ), {"id": _hex(rid), "school": school_id, "student": student_id,
        "item": _hex(item_id), "comp": competency_id,
        "session": _hex(session_id) if session_id else None, "created": created_at})


def test_upgrade_0015_dedoublonne_puis_pose_la_contrainte():
    # Base au niveau 0014 contenant des doublons (session_id, item_id) — exactement
    # l'état produit par l'ancien bug de garde non atomique : l'upgrade doit passer,
    # garder la réponse la plus ANCIENNE par couple, et laisser les NULL multiples.
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
    url = f"sqlite:///{tmp.name}"
    old_env = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        cfg = _alembic_cfg()
        command.upgrade(cfg, "0014_consumed_token")

        engine = sa.create_engine(url)   # PRAGMA foreign_keys OFF : lignes orphelines OK ici,
        # seul le comportement de la migration sur la table response est sous test.
        school, student, comp = _hex(uuid.uuid4()), _hex(uuid.uuid4()), _hex(uuid.uuid4())
        sess1, item1, item2 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        keep_id = uuid.uuid4()
        common = dict(school_id=school, student_id=student, competency_id=comp)
        with engine.begin() as conn:
            # 3 doublons (sess1, item1) — seule la plus ancienne doit survivre
            _insert_response(conn, rid=keep_id, session_id=sess1, item_id=item1,
                             created_at="2026-01-01 08:00:00", **common)
            _insert_response(conn, rid=uuid.uuid4(), session_id=sess1, item_id=item1,
                             created_at="2026-01-02 08:00:00", **common)
            _insert_response(conn, rid=uuid.uuid4(), session_id=sess1, item_id=item1,
                             created_at="2026-01-03 08:00:00", **common)
            # 1 réponse saine sur un autre item — intacte
            _insert_response(conn, rid=uuid.uuid4(), session_id=sess1, item_id=item2,
                             created_at="2026-01-01 09:00:00", **common)
            # 2 réponses HORS session (session_id NULL) sur le même item — les NULL
            # multiples restent LIBRES (seeds, moteur direct), jamais dédoublonnés
            _insert_response(conn, rid=uuid.uuid4(), session_id=None, item_id=item1,
                             created_at="2026-01-01 10:00:00", **common)
            _insert_response(conn, rid=uuid.uuid4(), session_id=None, item_id=item1,
                             created_at="2026-01-01 11:00:00", **common)

        command.upgrade(cfg, "head")     # ne doit PAS échouer malgré les doublons

        with engine.connect() as conn:
            rows = conn.execute(sa.text(
                "SELECT id FROM response WHERE session_id = :s AND item_id = :i"
            ), {"s": _hex(sess1), "i": _hex(item1)}).fetchall()
            assert len(rows) == 1                       # dédoublonné…
            assert rows[0][0] == _hex(keep_id)          # … en gardant la plus ancienne
            n_item2 = conn.execute(sa.text(
                "SELECT COUNT(*) FROM response WHERE item_id = :i"), {"i": _hex(item2)}
            ).scalar_one()
            assert n_item2 == 1                         # ligne saine intacte
            n_null = conn.execute(sa.text(
                "SELECT COUNT(*) FROM response WHERE session_id IS NULL")).scalar_one()
            assert n_null == 2                          # NULL multiples préservés
        # la contrainte est bien posée : un nouveau doublon est rejeté
        with engine.begin() as conn:
            try:
                _insert_response(conn, rid=uuid.uuid4(), session_id=sess1, item_id=item1,
                                 created_at="2026-01-04 08:00:00", **common)
                assert False, "doublon (session_id, item_id) aurait dû être rejeté"
            except sa.exc.IntegrityError:
                pass
        engine.dispose()
    finally:
        if old_env is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old_env
        os.unlink(tmp.name)


def test_migrations_reversibles_de_0016_a_0013():
    # downgrade 0016 → 0013 puis re-upgrade head : la chaîne reste praticable, y compris
    # 0014 (consumed_token créée directement en timezone-aware — revue 2026-07-08).
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
    url = f"sqlite:///{tmp.name}"
    old_env = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        cfg = _alembic_cfg()
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "0013_drop_direct_auth")
        command.upgrade(cfg, "head")
        # sanity : la table anti-rejeu et son index de purge ont bien été recréés
        engine = sa.create_engine(url)
        insp = sa.inspect(engine)
        assert "consumed_token" in insp.get_table_names()
        assert any(ix["name"] == "ix_consumed_token_expires_at"
                   for ix in insp.get_indexes("consumed_token"))
        engine.dispose()
    finally:
        if old_env is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old_env
        os.unlink(tmp.name)


def test_role_linguist_migration_upgrade_downgrade():
    # 0017 ajoute la valeur 'linguist' à l'enum RBAC `role`. Sur SQLite (native_enum sans
    # CHECK), la colonne role est un VARCHAR : l'upgrade est un no-op de schéma, mais on
    # vérifie que la chaîne monte à head, qu'une membership `linguist` s'insère, et que le
    # downgrade→re-upgrade reste praticable (no-op assumé côté downgrade).
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
    url = f"sqlite:///{tmp.name}"
    old_env = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        cfg = _alembic_cfg()
        command.upgrade(cfg, "head")            # 0017 inclus
        engine = sa.create_engine(url)
        with engine.begin() as conn:
            uid = _hex(uuid.uuid4())
            conn.execute(sa.text(
                "INSERT INTO app_user (id, email, is_active) VALUES (:id, :e, 1)"
            ), {"id": uid, "e": "ling@atlas.io"})
            # La valeur 'linguist' est acceptée par la colonne role.
            conn.execute(sa.text(
                "INSERT INTO membership (id, user_id, role) VALUES (:id, :u, 'linguist')"
            ), {"id": _hex(uuid.uuid4()), "u": uid})
        with engine.connect() as conn:
            role = conn.execute(sa.text(
                "SELECT role FROM membership WHERE user_id = :u"), {"u": uid}).scalar_one()
            assert role == "linguist"
        # downgrade d'un cran puis re-upgrade : la chaîne reste réversible.
        command.downgrade(cfg, "0016_timestamptz")
        command.upgrade(cfg, "head")
        engine.dispose()
    finally:
        if old_env is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old_env
        os.unlink(tmp.name)


def test_0019_schema_from_scratch_coherent_avec_les_modeles():
    # DoD B2/C-0 : `alembic upgrade head` sur base VIERGE doit produire EXACTEMENT le
    # schéma des modèles (create_all) — tables, colonnes, nullabilité, PK/FK/index/UNIQUE
    # des objets 0019. Une divergence = dérive migration/modèles, invisible dans les
    # tests applicatifs (qui créent le schéma via Base.metadata, jamais via Alembic).
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
    url = f"sqlite:///{tmp.name}"
    old_env = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        command.upgrade(_alembic_cfg(), "head")
        # import de TOUS les modules modèles pour peupler Base.metadata
        from src.models import audit, competency, curriculum, item, measurement, org, session  # noqa: F401
        from src.models.base import Base

        engine = sa.create_engine(url)
        insp = sa.inspect(engine)
        migrated = set(insp.get_table_names()) - {"alembic_version"}
        assert migrated == set(Base.metadata.tables), (
            f"tables divergentes : migration seule {migrated - set(Base.metadata.tables)}, "
            f"modèles seuls {set(Base.metadata.tables) - migrated}"
        )
        for t in sorted(migrated):
            model_cols = {c.name: c for c in Base.metadata.tables[t].columns}
            mig_cols = {c["name"]: c for c in insp.get_columns(t)}
            assert set(model_cols) == set(mig_cols), (
                f"{t} : colonnes divergentes {set(model_cols) ^ set(mig_cols)}"
            )
            for n, mc in model_cols.items():
                assert bool(mc.nullable) == bool(mig_cols[n]["nullable"]), (
                    f"{t}.{n} : nullable modèle={mc.nullable} vs migration={mig_cols[n]['nullable']}"
                )
        # contraintes structurantes des tables 0019 (crosswalk B2)
        uqs = insp.get_unique_constraints("curriculum_standard")
        assert any(u["name"] == "uq_curriculum_standard_framework_code"
                   and u["column_names"] == ["framework_id", "code"] for u in uqs)   # refonte C1
        assert insp.get_pk_constraint("competency_curriculum_map")["constrained_columns"] == [
            "competency_id", "standard_id"]
        assert any(ix["name"] == "ix_ccm_standard" and ix["column_names"] == ["standard_id"]
                   for ix in insp.get_indexes("competency_curriculum_map"))
        fks = {f["referred_table"]: f["options"] for f in
               insp.get_foreign_keys("competency_curriculum_map")}
        assert fks == {"competency": {"ondelete": "CASCADE"},
                       "curriculum_standard": {"ondelete": "CASCADE"},
                       "app_user": {"ondelete": "SET NULL"}}          # reviewed_by (refonte C1)
        engine.dispose()
    finally:
        if old_env is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old_env
        os.unlink(tmp.name)


def test_0019_defauts_sur_lignes_existantes_et_reversibilite():
    # Les lignes ANTÉRIEURES à 0019 sont réputées anglaises (server_default 'en' —
    # seule l'UI EN a servi des réponses avant) et les tenants existants restent en
    # vue neutre 'ATLAS' (zéro régression B3). Puis downgrade → re-upgrade praticable.
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
    url = f"sqlite:///{tmp.name}"
    old_env = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        cfg = _alembic_cfg()
        command.upgrade(cfg, "0018_legal_hold")   # état AVANT le lot B/C-0

        engine = sa.create_engine(url)
        school, student, comp = _hex(uuid.uuid4()), _hex(uuid.uuid4()), _hex(uuid.uuid4())
        sess, org = uuid.uuid4(), uuid.uuid4()
        with engine.begin() as conn:
            conn.execute(sa.text(
                "INSERT INTO organization (id, name) VALUES (:id, 'Legacy Org')"
            ), {"id": _hex(org)})
            conn.execute(sa.text(
                "INSERT INTO assessment_session (id, school_id, student_id, status, started_at) "
                "VALUES (:id, :school, :student, 'active', '2026-01-01 08:00:00')"
            ), {"id": _hex(sess), "school": school, "student": student})
            _insert_response(conn, rid=uuid.uuid4(), session_id=sess, item_id=uuid.uuid4(),
                             created_at="2026-01-01 08:05:00", school_id=school,
                             student_id=student, competency_id=comp)

        command.upgrade(cfg, "head")              # 0019 : colonnes + tables crosswalk

        with engine.connect() as conn:
            assert conn.execute(sa.text("SELECT language FROM response")).scalar_one() == "en"
            assert conn.execute(sa.text("SELECT locale FROM assessment_session")).scalar_one() == "en"
            # refonte C1 (0030) : la vue neutre ATLAS = framework NULL
            assert conn.execute(sa.text(
                "SELECT curriculum_framework_id FROM organization")).scalar_one() is None

        # réversibilité : le downgrade retire tout, le re-upgrade repasse
        command.downgrade(cfg, "0018_legal_hold")
        insp = sa.inspect(engine)   # inspecteur NEUF : pas de cache d'avant-downgrade
        assert "curriculum_standard" not in insp.get_table_names()
        assert "competency_curriculum_map" not in insp.get_table_names()
        assert "curriculum_framework" not in insp.get_table_names()
        assert not any(c["name"] == "language" for c in insp.get_columns("response"))
        assert not any(c["name"] == "locale" for c in insp.get_columns("assessment_session"))
        assert not any(c["name"] in ("curriculum_view", "curriculum_framework_id") for c in insp.get_columns("organization"))
        command.upgrade(cfg, "head")
        engine.dispose()
    finally:
        if old_env is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old_env
        os.unlink(tmp.name)


def test_0021_0022_roles_refonte_et_portee_dept_lead_reversibles():
    # Refonte A1 : 0021 ajoute dept_lead/group_admin à l'enum `role` (no-op SQLite, ALTER TYPE
    # Postgres) ; 0022 ajoute classroom.grade (indexé) et la table dept_lead_scope. On vérifie
    # que les nouvelles valeurs et colonnes s'écrivent, puis que downgrade → 0020 retire tout
    # le schéma de 0022 et que le re-upgrade repasse. La cohérence colonne à colonne avec les
    # modèles est couverte par test_0019_schema_from_scratch_coherent_avec_les_modeles.
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
    url = f"sqlite:///{tmp.name}"
    old_env = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        cfg = _alembic_cfg()
        command.upgrade(cfg, "head")
        engine = sa.create_engine(url)
        insp = sa.inspect(engine)
        assert "dept_lead_scope" in insp.get_table_names()
        assert any(c["name"] == "grade" and c["nullable"] for c in insp.get_columns("classroom"))
        assert any(ix["name"] == "ix_classroom_grade" and ix["column_names"] == ["grade"]
                   for ix in insp.get_indexes("classroom"))
        assert insp.get_pk_constraint("dept_lead_scope")["constrained_columns"] == ["membership_id", "grade"]
        fks = insp.get_foreign_keys("dept_lead_scope")
        assert len(fks) == 1 and fks[0]["referred_table"] == "membership" \
            and fks[0]["options"] == {"ondelete": "CASCADE"}
        with engine.begin() as conn:
            uid, mid, school = _hex(uuid.uuid4()), _hex(uuid.uuid4()), _hex(uuid.uuid4())
            conn.execute(sa.text("INSERT INTO school (id, name) VALUES (:id, 'S')"), {"id": school})
            conn.execute(sa.text(
                "INSERT INTO app_user (id, email, is_active) VALUES (:id, 'lead@atlas.io', 1)"), {"id": uid})
            conn.execute(sa.text(
                "INSERT INTO membership (id, user_id, role, school_id) VALUES (:id, :u, 'dept_lead', :s)"
            ), {"id": mid, "u": uid, "s": school})
            conn.execute(sa.text(
                "INSERT INTO membership (id, user_id, role) VALUES (:id, :u, 'group_admin')"
            ), {"id": _hex(uuid.uuid4()), "u": uid})
            conn.execute(sa.text(
                "INSERT INTO dept_lead_scope (membership_id, grade) VALUES (:m, 4)"), {"m": mid})
            conn.execute(sa.text(
                "INSERT INTO classroom (id, school_id, name, grade) VALUES (:id, :s, '4A', 4)"
            ), {"id": _hex(uuid.uuid4()), "s": school})
        with engine.connect() as conn:
            roles = set(conn.execute(sa.text("SELECT role FROM membership")).scalars())
            assert roles == {"dept_lead", "group_admin"}
            assert conn.execute(sa.text("SELECT grade FROM classroom")).scalar_one() == 4

        command.downgrade(cfg, "0020_enrich_kind")
        insp = sa.inspect(engine)   # inspecteur NEUF
        assert "dept_lead_scope" not in insp.get_table_names()
        assert not any(c["name"] == "grade" for c in insp.get_columns("classroom"))
        assert not any(ix["name"] == "ix_classroom_grade" for ix in insp.get_indexes("classroom"))
        command.upgrade(cfg, "head")
        insp = sa.inspect(engine)
        assert "dept_lead_scope" in insp.get_table_names()
        engine.dispose()
    finally:
        if old_env is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old_env
        os.unlink(tmp.name)


def test_0023_item_versions_et_item_flag_reversibles():
    # Refonte A2 : colonnes de version sur item (défauts serveur pour les lignes existantes) +
    # table item_flag. La cohérence colonne à colonne avec les modèles est couverte par
    # test_0019_schema_from_scratch_coherent_avec_les_modeles.
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
    url = f"sqlite:///{tmp.name}"
    old_env = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        cfg = _alembic_cfg()
        command.upgrade(cfg, "0022_classroom_grade_dept_scope")
        engine = sa.create_engine(url)
        comp, item_id = _hex(uuid.uuid4()), _hex(uuid.uuid4())
        with engine.begin() as conn:
            conn.execute(sa.text(
                "INSERT INTO competency (id, code, label_en, label_ar, subject, grade, difficulty_prior, status, "
                "created_at, updated_at) VALUES (:id, 'M.A', 'a', 'b', 'MATH', 4, 1200.0, 'active', "
                "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"), {"id": comp})
            conn.execute(sa.text(
                "INSERT INTO item (id, competency_id, content_en, content_ar, answer_format, difficulty_prior, "
                "difficulty_elo, n_responses, context_tags, status, provenance, ar_validated, created_at, updated_at) "
                "VALUES (:id, :c, '{}', '{}', 'MCQ', 1200.0, 1200.0, 0, '{}', 'active', '{}', 1, "
                "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"), {"id": item_id, "c": comp})
        command.upgrade(cfg, "head")
        with engine.connect() as conn:
            row = conn.execute(sa.text(
                "SELECT origin, version, template_key, supersedes_id FROM item")).one()
            assert tuple(row) == ("atlas_template", 1, None, None)       # défauts sur l'existant
        with engine.begin() as conn:
            conn.execute(sa.text(
                "INSERT INTO item_flag (id, item_id, reason, status, created_at) "
                "VALUES (:id, :i, 'wrong_answer_key', 'open', '2026-01-02 00:00:00')"),
                {"id": _hex(uuid.uuid4()), "i": item_id})
        insp = sa.inspect(engine)
        fks = {f["referred_table"]: f["options"] for f in insp.get_foreign_keys("item_flag")}
        assert fks["item"] == {"ondelete": "CASCADE"} and fks["school"] == {"ondelete": "SET NULL"}
        assert any(ix["name"] == "ix_item_template_key" for ix in insp.get_indexes("item"))

        command.downgrade(cfg, "0022_classroom_grade_dept_scope")
        insp = sa.inspect(engine)
        assert "item_flag" not in insp.get_table_names()
        cols = {c["name"] for c in insp.get_columns("item")}
        assert not ({"origin", "template_key", "version", "supersedes_id", "calibration_reset_at",
                     "owner_school_id"} & cols)
        with engine.connect() as conn:                                  # la ligne item survit
            assert conn.execute(sa.text("SELECT COUNT(*) FROM item")).scalar_one() == 1
        command.upgrade(cfg, "head")
        engine.dispose()
    finally:
        if old_env is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old_env
        os.unlink(tmp.name)


def test_0024_role_content_reviewer_reversible():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
    url = f"sqlite:///{tmp.name}"
    old_env = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        cfg = _alembic_cfg()
        command.upgrade(cfg, "head")
        engine = sa.create_engine(url)
        with engine.begin() as conn:
            uid = _hex(uuid.uuid4())
            conn.execute(sa.text("INSERT INTO app_user (id, email, is_active) VALUES (:id, 'rev@atlas.io', 1)"), {"id": uid})
            conn.execute(sa.text("INSERT INTO membership (id, user_id, role) VALUES (:id, :u, 'content_reviewer')"),
                         {"id": _hex(uuid.uuid4()), "u": uid})
        with engine.connect() as conn:
            assert conn.execute(sa.text("SELECT role FROM membership")).scalar_one() == "content_reviewer"
        command.downgrade(cfg, "0023_item_versions_flags")
        command.upgrade(cfg, "head")
        engine.dispose()
    finally:
        if old_env is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old_env
        os.unlink(tmp.name)


def test_0025_checkin_reversible():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
    url = f"sqlite:///{tmp.name}"
    old_env = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        cfg = _alembic_cfg()
        command.upgrade(cfg, "head")
        engine = sa.create_engine(url)
        insp = sa.inspect(engine)
        assert "checkin" in insp.get_table_names()
        assert any(c["name"] == "checkin_id" for c in insp.get_columns("assessment_session"))
        fks = {f["referred_table"]: f["options"] for f in insp.get_foreign_keys("checkin")}
        assert fks["classroom"] == {"ondelete": "CASCADE"} and fks["app_user"] == {"ondelete": "SET NULL"}
        assert any(f["referred_table"] == "checkin" and f["options"] == {"ondelete": "SET NULL"}
                   for f in insp.get_foreign_keys("assessment_session"))
        with engine.begin() as conn:
            school, cls = _hex(uuid.uuid4()), _hex(uuid.uuid4())
            conn.execute(sa.text("INSERT INTO school (id, name) VALUES (:id, 'S')"), {"id": school})
            conn.execute(sa.text("INSERT INTO classroom (id, school_id, name) VALUES (:id, :s, '4B')"), {"id": cls, "s": school})
            conn.execute(sa.text(
                "INSERT INTO checkin (id, school_id, classroom_id, kind, code, status, opened_at) "
                "VALUES (:id, :s, :c, 'full', '1234', 'open', '2026-01-01 08:00:00')"),
                {"id": _hex(uuid.uuid4()), "s": school, "c": cls})
        command.downgrade(cfg, "0024_role_content_reviewer")
        insp = sa.inspect(engine)
        assert "checkin" not in insp.get_table_names()
        assert not any(c["name"] == "checkin_id" for c in insp.get_columns("assessment_session"))
        command.upgrade(cfg, "head")
        engine.dispose()
    finally:
        if old_env is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old_env
        os.unlink(tmp.name)


def test_0026_weekly_plan_reversible_and_checkin_fk():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
    url = f"sqlite:///{tmp.name}"
    old_env = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        cfg = _alembic_cfg()
        command.upgrade(cfg, "head")
        engine = sa.create_engine(url)
        insp = sa.inspect(engine)
        assert {"weekly_plan", "plan_action", "plan_action_member", "proof"} <= set(insp.get_table_names())
        assert any(f["referred_table"] == "plan_action" and f["options"] == {"ondelete": "SET NULL"}
                   for f in insp.get_foreign_keys("checkin"))
        fks = {f["referred_table"]: f["options"] for f in insp.get_foreign_keys("plan_action_member")}
        assert fks["student"] == {"ondelete": "CASCADE"} and fks["plan_action"] == {"ondelete": "CASCADE"}
        assert insp.get_pk_constraint("plan_action_member")["constrained_columns"] == ["action_id", "student_id"]
        command.downgrade(cfg, "0025_checkin")
        insp = sa.inspect(engine)
        assert not ({"weekly_plan", "plan_action", "plan_action_member", "proof"} & set(insp.get_table_names()))
        assert not any(f["referred_table"] == "plan_action" for f in insp.get_foreign_keys("checkin"))
        command.upgrade(cfg, "head")
        engine.dispose()
    finally:
        if old_env is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old_env
        os.unlink(tmp.name)


def test_0027_0028_response_selected_and_mini_lesson_reversible():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
    url = f"sqlite:///{tmp.name}"
    old_env = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        cfg = _alembic_cfg()
        command.upgrade(cfg, "head")
        engine = sa.create_engine(url)
        insp = sa.inspect(engine)
        assert any(c["name"] == "selected" and c["nullable"] for c in insp.get_columns("response"))
        assert "mini_lesson" in insp.get_table_names()
        assert any(f["referred_table"] == "mini_lesson" and f["options"] == {"ondelete": "SET NULL"}
                   for f in insp.get_foreign_keys("plan_action"))
        assert any(u["name"] == "uq_mini_lesson_key" for u in insp.get_unique_constraints("mini_lesson"))
        command.downgrade(cfg, "0026_weekly_plan")
        insp = sa.inspect(engine)
        assert "mini_lesson" not in insp.get_table_names()
        assert not any(c["name"] == "selected" for c in insp.get_columns("response"))
        assert not any(f["referred_table"] == "mini_lesson" for f in insp.get_foreign_keys("plan_action"))
        command.upgrade(cfg, "head")
        engine.dispose()
    finally:
        if old_env is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old_env
        os.unlink(tmp.name)


def test_0029_school_plan_mail_reversible():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
    url = f"sqlite:///{tmp.name}"
    old_env = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        cfg = _alembic_cfg()
        command.upgrade(cfg, "head")
        engine = sa.create_engine(url)
        cols = {c["name"] for c in sa.inspect(engine).get_columns("school")}
        assert {"country", "plan_mail_weekday", "plan_mail_hour", "timezone"} <= cols
        command.downgrade(cfg, "0028_mini_lesson")
        cols = {c["name"] for c in sa.inspect(engine).get_columns("school")}
        assert not ({"country", "plan_mail_weekday", "plan_mail_hour", "timezone"} & cols)
        command.upgrade(cfg, "head")
        engine.dispose()
    finally:
        if old_env is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old_env
        os.unlink(tmp.name)


def test_0030_frameworks_table_migrates_data_and_downgrade_is_guarded():
    # Refonte C1 : à 0029, une org en vue CCSS_M et des standards CCSS_M / UK_NC ; après 0030 les
    # 3 frameworks historiques existent (publiés, ids stables), les standards pointent le bon
    # framework, l'org pointe CCSS_M, ATLAS → NULL ; downgrade → enums recopiés ; un framework
    # étranger bloque le downgrade.
    import uuid as _uuid
    from src.models.curriculum import legacy_framework_id
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
    url = f"sqlite:///{tmp.name}"
    old_env = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        cfg = _alembic_cfg()
        command.upgrade(cfg, "0029_school_plan_mail")
        engine = sa.create_engine(url)
        org_ccss, org_atlas, std_c, std_uk = (_hex(_uuid.uuid4()) for _ in range(4))
        with engine.begin() as conn:
            conn.execute(sa.text("INSERT INTO organization (id, name, curriculum_view) VALUES (:id, 'A', 'CCSS_M')"), {"id": org_ccss})
            conn.execute(sa.text("INSERT INTO organization (id, name, curriculum_view) VALUES (:id, 'B', 'ATLAS')"), {"id": org_atlas})
            conn.execute(sa.text("INSERT INTO curriculum_standard (id, framework, code, label_en, label_ar) VALUES (:id, 'CCSS_M', '4.NF.A.1', 'a', 'b')"), {"id": std_c})
            conn.execute(sa.text("INSERT INTO curriculum_standard (id, framework, code, label_en, label_ar) VALUES (:id, 'UK_NC', 'Y5', 'a', 'b')"), {"id": std_uk})
        command.upgrade(cfg, "head")
        with engine.connect() as conn:
            rows = conn.execute(sa.text("SELECT key, status FROM curriculum_framework ORDER BY key")).fetchall()
            assert [tuple(r) for r in rows] == [("CCSS_M", "published"), ("MOE_UAE", "published"), ("UK_NC", "published")]
            fw_c = conn.execute(sa.text("SELECT id FROM curriculum_framework WHERE key='CCSS_M'")).scalar_one()
            assert fw_c == _hex(legacy_framework_id("CCSS_M"))
            assert conn.execute(sa.text("SELECT framework_id FROM curriculum_standard WHERE id=:i"), {"i": std_c}).scalar_one() == fw_c
            assert conn.execute(sa.text("SELECT framework_id FROM curriculum_standard WHERE id=:i"), {"i": std_uk}).scalar_one() == _hex(legacy_framework_id("UK_NC"))
            assert conn.execute(sa.text("SELECT curriculum_framework_id FROM organization WHERE id=:i"), {"i": org_ccss}).scalar_one() == fw_c
            assert conn.execute(sa.text("SELECT curriculum_framework_id FROM organization WHERE id=:i"), {"i": org_atlas}).scalar_one() is None
            cols = {c["name"] for c in sa.inspect(engine).get_columns("competency_curriculum_map")}
            assert {"reviewed_by", "reviewed_at", "suggested"} <= cols
        # un framework importé (hors enum) bloque le downgrade
        with engine.begin() as conn:
            conn.execute(sa.text("INSERT INTO curriculum_framework (id, key, name_en, name_ar, status, imported_at) "
                                 "VALUES (:id, 'IB_PYP', 'IB', 'IB', 'draft', '2026-01-01 00:00:00')"), {"id": _hex(_uuid.uuid4())})
        try:
            command.downgrade(cfg, "0029_school_plan_mail")
            assert False, "downgrade aurait dû être refusé"
        except RuntimeError as e:
            assert "IB_PYP" in str(e)
        with engine.begin() as conn:
            conn.execute(sa.text("DELETE FROM curriculum_framework WHERE key='IB_PYP'"))
        command.downgrade(cfg, "0029_school_plan_mail")
        with engine.connect() as conn:
            assert conn.execute(sa.text("SELECT curriculum_view FROM organization WHERE id=:i"), {"i": org_ccss}).scalar_one() == "CCSS_M"
            assert conn.execute(sa.text("SELECT curriculum_view FROM organization WHERE id=:i"), {"i": org_atlas}).scalar_one() == "ATLAS"
            assert conn.execute(sa.text("SELECT framework FROM curriculum_standard WHERE id=:i"), {"i": std_uk}).scalar_one() == "UK_NC"
        insp = sa.inspect(engine)
        assert "curriculum_framework" not in insp.get_table_names()
        command.upgrade(cfg, "head")
        engine.dispose()
    finally:
        if old_env is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old_env
        os.unlink(tmp.name)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} tests OK")
