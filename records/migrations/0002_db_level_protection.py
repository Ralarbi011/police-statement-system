"""
Database-level tamper protection (PostgreSQL only).

The application already refuses to change signed statements, attachments and
audit entries. These triggers enforce the same rules inside the database, so
even someone with direct SQL access through the application's DB account
cannot silently alter evidence.
"""
from django.db import migrations

FORWARD_SQL = """
CREATE OR REPLACE FUNCTION pss_block_change() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Tamper protection: % on % is not permitted', TG_OP, TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION pss_protect_statement() RETURNS trigger AS $$
BEGIN
    IF OLD.status = 'FINALIZED' THEN
        RAISE EXCEPTION 'Tamper protection: signed statement % cannot be % ', OLD.id, lower(TG_OP);
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS pss_statement_guard ON records_statement;
CREATE TRIGGER pss_statement_guard BEFORE UPDATE OR DELETE ON records_statement
    FOR EACH ROW EXECUTE FUNCTION pss_protect_statement();

DROP TRIGGER IF EXISTS pss_attachment_guard ON records_attachment;
CREATE TRIGGER pss_attachment_guard BEFORE UPDATE OR DELETE ON records_attachment
    FOR EACH ROW EXECUTE FUNCTION pss_block_change();

DROP TRIGGER IF EXISTS pss_casenote_guard ON records_casenote;
CREATE TRIGGER pss_casenote_guard BEFORE UPDATE OR DELETE ON records_casenote
    FOR EACH ROW EXECUTE FUNCTION pss_block_change();

DROP TRIGGER IF EXISTS pss_auditlog_guard ON audit_auditlog;
CREATE TRIGGER pss_auditlog_guard BEFORE UPDATE OR DELETE ON audit_auditlog
    FOR EACH ROW EXECUTE FUNCTION pss_block_change();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS pss_statement_guard ON records_statement;
DROP TRIGGER IF EXISTS pss_attachment_guard ON records_attachment;
DROP TRIGGER IF EXISTS pss_casenote_guard ON records_casenote;
DROP TRIGGER IF EXISTS pss_auditlog_guard ON audit_auditlog;
DROP FUNCTION IF EXISTS pss_protect_statement();
DROP FUNCTION IF EXISTS pss_block_change();
"""


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(FORWARD_SQL)


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE_SQL)


class Migration(migrations.Migration):
    dependencies = [
        ("records", "0001_initial"),
        ("audit", "0001_initial"),
    ]
    operations = [migrations.RunPython(forwards, backwards)]
