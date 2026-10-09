import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { after, before, test } from 'node:test';
import { PGlite } from '@electric-sql/pglite';

// Real PostgreSQL, with only Supabase's Auth table/roles supplied by the fixture.
const db = new PGlite();
const alice = '00000000-0000-0000-0000-000000000001';
const bob = '00000000-0000-0000-0000-000000000002';

before(async () => {
    await db.exec(`
        create role anon nologin;
        create role authenticated nologin;
        create schema auth;
        create table auth.users (id uuid primary key, raw_user_meta_data jsonb);
        create function auth.uid() returns uuid language sql stable as $$
            select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid;
        $$;
        grant usage on schema public, auth to anon, authenticated;
        grant execute on function auth.uid() to anon, authenticated;
        insert into auth.users values ('${alice}', '{"display_name":"Alice"}');
    `);
    await db.exec(await readFile(new URL('../../supabase/migrations/20261009000000_create_profiles.sql', import.meta.url), 'utf8'));
    await db.query('insert into auth.users values ($1, $2)', [bob, { display_name: 'Bob' }]);
});

after(async () => { await db.close(); });

async function asUser(role, id, callback) {
    await db.exec(`set role ${role}`);
    await db.query("select set_config('request.jwt.claim.sub', $1, false)", [id || '']);
    try { await callback(); }
    finally { await db.exec('reset role'); }
}

test('migration backfills existing users and creates profiles on signup', async () => {
    const { rows } = await db.query('select id, display_name from public.profiles order by id');
    assert.deepEqual(rows, [{ id: alice, display_name: 'Alice' }, { id: bob, display_name: 'Bob' }]);
});

test('authenticated users can read only their own profile', async () => {
    await asUser('authenticated', alice, async () => {
        const { rows } = await db.query('select id from public.profiles');
        assert.deepEqual(rows, [{ id: alice }]);
        assert.deepEqual((await db.query('select id from public.profiles where id = $1', [bob])).rows, []);
    });
    await asUser('authenticated', bob, async () => {
        assert.deepEqual((await db.query('select id from public.profiles')).rows, [{ id: bob }]);
    });
});

test('anonymous requests have no access, even if a user ID is supplied', async () => {
    await asUser('anon', alice, async () => {
        await assert.rejects(db.query('select * from public.profiles'), /permission denied/);
    });
    await asUser('authenticated', '', async () => {
        assert.deepEqual((await db.query('select * from public.profiles')).rows, []);
    });
});

test('own display name can change; another user and immutable fields cannot', async () => {
    const before = (await db.query('select updated_at from public.profiles where id = $1', [alice])).rows[0].updated_at;
    await asUser('authenticated', alice, async () => {
        assert.equal((await db.query('update public.profiles set display_name = $1 where id = $2 returning id', ['Alice Updated', alice])).rows.length, 1);
        assert.deepEqual((await db.query('update public.profiles set display_name = $1 where id = $2 returning id', ['Hijacked', bob])).rows, []);
        await assert.rejects(db.query('update public.profiles set id = $1 where id = $2', [bob, alice]), /permission denied/);
        await assert.rejects(db.query('update public.profiles set created_at = now()'), /permission denied/);
        await assert.rejects(db.query('update public.profiles set updated_at = now()'), /permission denied/);
        await assert.rejects(db.query('update public.profiles set display_name = $1', [' ']), /check constraint/);
        await assert.rejects(db.query('update public.profiles set display_name = $1', ['x'.repeat(101)]), /check constraint/);
    });
    const { rows } = await db.query('select display_name, updated_at from public.profiles where id = $1', [alice]);
    assert.equal(rows[0].display_name, 'Alice Updated');
    assert.ok(rows[0].updated_at > before);
});

test('clients cannot create/delete profiles or directly invoke the signup trigger', async () => {
    await asUser('authenticated', alice, async () => {
        await assert.rejects(db.query('insert into public.profiles (id, display_name) values ($1, $2)', ['00000000-0000-0000-0000-000000000003', 'Injected']), /permission denied/);
        await assert.rejects(db.query('delete from public.profiles'), /permission denied/);
        await assert.rejects(db.query('select public.bridge_create_profile()'), /permission denied/);
    });
});

test('signup handles missing or oversized metadata; deleting auth user cascades', async () => {
    const id = '00000000-0000-0000-0000-000000000003';
    await db.query('insert into auth.users values ($1, $2)', [id, { display_name: ' '.repeat(10) }]);
    assert.equal((await db.query('select display_name from public.profiles where id = $1', [id])).rows[0].display_name, 'Accountant');
    await db.query('delete from auth.users where id = $1', [id]);
    assert.deepEqual((await db.query('select id from public.profiles where id = $1', [id])).rows, []);
    await db.query('insert into auth.users values ($1, $2)', [id, { display_name: 'x'.repeat(200) }]);
    assert.equal((await db.query('select display_name from public.profiles where id = $1', [id])).rows[0].display_name.length, 100);
});
