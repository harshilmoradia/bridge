import assert from 'node:assert/strict';
import test from 'node:test';
import { isPublicSupabaseKey, isSupabaseUrl, validateAuthFields } from '../src/lib/auth.ts';

const valid = { email: 'person@example.com', password: 'a-long-password', confirmPassword: 'a-long-password', displayName: 'Test User' };

test('signup and password recovery reject mismatched passwords', () => {
    for (const mode of ['signup', 'update'] as const) {
        assert.equal(validateAuthFields(mode, { ...valid, confirmPassword: 'different' }), 'Passwords do not match.');
        assert.equal(validateAuthFields(mode, { ...valid, password: 'short' }), 'Use a password with at least 12 characters.');
    }
    assert.equal(validateAuthFields('signup', valid), null);
    assert.equal(validateAuthFields('update', { ...valid, email: '' }), null);
});

test('login accepts existing shorter passwords while signup validates names and email', () => {
    assert.equal(validateAuthFields('login', { ...valid, password: 'old' }), null);
    assert.match(validateAuthFields('signup', { ...valid, displayName: ' ' }) || '', /name/);
    assert.match(validateAuthFields('signup', { ...valid, displayName: 'x'.repeat(101) }) || '', /name/);
    assert.match(validateAuthFields('reset', { ...valid, email: 'invalid' }) || '', /email/);
    assert.equal(validateAuthFields('reset', { ...valid, password: '' }), null);
});

test('only public Supabase keys are accepted in frontend configuration', () => {
    const jwt = (role: string) => 'header.' + Buffer.from(JSON.stringify({ role })).toString('base64url') + '.signature';
    assert.equal(isPublicSupabaseKey('sb_publishable_example'), true);
    assert.equal(isPublicSupabaseKey(jwt('anon')), true);
    for (const key of ['', 'invalid', 'sb_publishable_', 'sb_secret_example', jwt('service_role'), jwt('authenticated')]) {
        assert.equal(isPublicSupabaseKey(key), false);
    }
});

test('Supabase configuration accepts only a secure project origin or localhost', () => {
    for (const url of ['https://example.supabase.co', 'http://127.0.0.1:54321', 'http://localhost:54321/']) assert.equal(isSupabaseUrl(url), true);
    for (const url of ['', 'not-a-url', 'http://example.supabase.co', 'https://user:password@example.supabase.co', 'https://example.supabase.co/auth/v1', 'https://example.supabase.co?key=value']) assert.equal(isSupabaseUrl(url), false);
});
