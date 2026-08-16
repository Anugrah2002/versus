/**
 * Versus Cloudflare Edge Worker API.
 * Proxies and edge-caches news feed responses to protect Firebase Firestore 50k read limits.
 */

export interface Env {
  FIREBASE_PROJECT_ID: string;
  CACHE_TTL_SECONDS: string;
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    const { pathname, searchParams } = url;

    // Handle CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        headers: {
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Methods': 'GET, OPTIONS',
          'Access-Control-Allow-Headers': 'Content-Type, Authorization',
        },
      });
    }

    // Health check endpoint
    if (pathname === '/health' || pathname === '/') {
      return jsonResponse({ status: 'ok', service: 'versus-edge-api', time: new Date().toISOString() });
    }

    // Edge cache lookup for GET requests
    const cache = caches.default;
    const cacheKey = new Request(url.toString(), request);
    let cachedResponse = await cache.match(cacheKey);
    if (cachedResponse) {
      const resp = new Response(cachedResponse.body, cachedResponse);
      resp.headers.set('X-Edge-Cache', 'HIT');
      return resp;
    }

    let response: Response;

    // Router
    if (pathname === '/api/feed') {
      response = await handleGetFeed(searchParams, env);
    } else if (pathname.startsWith('/api/articles/')) {
      const articleId = pathname.replace('/api/articles/', '');
      response = await handleGetArticleById(articleId, env);
    } else if (pathname === '/api/categories') {
      response = handleGetCategories();
    } else if (pathname === '/api/image-proxy') {
      return handleImageProxy(searchParams, ctx);
    } else {
      return jsonResponse({ error: 'Endpoint not found' }, 404);
    }

    // Add Edge Cache Headers (5-min edge TTL, 10-min stale-while-revalidate)
    const ttl = parseInt(env.CACHE_TTL_SECONDS || '300', 10);
    response.headers.set('Cache-Control', `public, max-age=${ttl}, s-maxage=${ttl}, stale-while-revalidate=600`);
    response.headers.set('X-Edge-Cache', 'MISS');
    response.headers.set('Access-Control-Allow-Origin', '*');

    // Store in Cloudflare Edge Cache
    ctx.waitUntil(cache.put(cacheKey, response.clone()));
    return response;
  },
};

function jsonResponse(data: any, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      'Content-Type': 'application/json',
      'Access-Control-Allow-Origin': '*',
      ...headers,
    },
  });
}

async function handleGetFeed(searchParams: URLSearchParams, env: Env): Promise<Response> {
  const category = searchParams.get('category');
  const limit = parseInt(searchParams.get('limit') || '20', 10);
  const projectId = env.FIREBASE_PROJECT_ID || 'versus-news';

  // Query Firestore via REST API
  const firestoreUrl = `https://firestore.googleapis.com/v1/projects/${projectId}/databases/(default)/documents/articles?pageSize=${limit}`;

  try {
    const res = await fetch(firestoreUrl);
    if (!res.ok) {
      return jsonResponse({ articles: [], error: `Firestore returned ${res.status}` }, 200);
    }

    const data: any = await res.json();
    const rawDocs = data.documents || [];

    const articles = rawDocs.map((doc: any) => parseFirestoreDocument(doc)).filter(Boolean);

    // Optional category filter
    const filtered = category
      ? articles.filter((a: any) => a.category?.toLowerCase() === category.toLowerCase())
      : articles;

    return jsonResponse({
      count: filtered.length,
      articles: filtered,
      cachedAt: new Date().toISOString(),
    });
  } catch (err: any) {
    return jsonResponse({ articles: [], error: err.message }, 500);
  }
}

async function handleGetArticleById(articleId: string, env: Env): Promise<Response> {
  const projectId = env.FIREBASE_PROJECT_ID || 'versus-news';
  const firestoreUrl = `https://firestore.googleapis.com/v1/projects/${projectId}/databases/(default)/documents/articles/${articleId}`;

  try {
    const res = await fetch(firestoreUrl);
    if (!res.ok) {
      return jsonResponse({ error: 'Article not found' }, 404);
    }
    const doc = await res.json();
    return jsonResponse(parseFirestoreDocument(doc));
  } catch (err: any) {
    return jsonResponse({ error: err.message }, 500);
  }
}

function handleGetCategories(): Response {
  return jsonResponse({
    categories: [
      { id: 'tech_ai', name: 'Tech & AI', slug: 'tech-ai', accentColor: '#00F0FF' },
      { id: 'work_economy', name: 'Work & Economy', slug: 'work-economy', accentColor: '#FF007A' },
      { id: 'business_policy', name: 'Business & Policy', slug: 'business-policy', accentColor: '#FFB800' },
      { id: 'space_science', name: 'Space & Science', slug: 'space-science', accentColor: '#00E5A3' },
      { id: 'automotive_energy', name: 'Automotive & Energy', slug: 'automotive-energy', accentColor: '#7000FF' },
      { id: 'world_affairs', name: 'World Affairs', slug: 'world-affairs', accentColor: '#FF3366' },
      { id: 'science_society', name: 'Science & Society', slug: 'science-society', accentColor: '#00C2FF' },
    ],
  });
}

async function handleImageProxy(searchParams: URLSearchParams, ctx: ExecutionContext): Promise<Response> {
  const imageUrl = searchParams.get('url');
  if (!imageUrl) {
    return jsonResponse({ error: 'Missing url parameter' }, 400);
  }

  try {
    const targetUrl = new URL(imageUrl);
    const originHost = targetUrl.hostname;

    // Fetch image from origin server-side to bypass client hotlink protection
    const imageRes = await fetch(imageUrl, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
        'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
        'Referer': `https://${originHost}/`,
      },
    });

    if (!imageRes.ok) {
      // Return 302 redirect to fallback placeholder if upstream image is dead
      return Response.redirect('https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&w=1080&q=80', 302);
    }

    const contentType = imageRes.headers.get('Content-Type') || 'image/jpeg';
    const proxyRes = new Response(imageRes.body, {
      status: 200,
      headers: {
        'Content-Type': contentType,
        'Access-Control-Allow-Origin': '*',
        'Cache-Control': 'public, max-age=604800, s-maxage=604800, immutable',
        'X-Image-Proxy': 'Cloudflare-Edge',
      },
    });

    return proxyRes;
  } catch (err: any) {
    return Response.redirect('https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&w=1080&q=80', 302);
  }
}

function parseFirestoreDocument(doc: any): any {
  if (!doc || !doc.fields) return null;
  const fields = doc.fields;
  const obj: any = {};

  for (const [key, val] of Object.entries<any>(fields)) {
    if (val.stringValue !== undefined) obj[key] = val.stringValue;
    else if (val.integerValue !== undefined) obj[key] = parseInt(val.integerValue, 10);
    else if (val.doubleValue !== undefined) obj[key] = parseFloat(val.doubleValue);
    else if (val.booleanValue !== undefined) obj[key] = val.booleanValue;
    else if (val.timestampValue !== undefined) obj[key] = val.timestampValue;
    else if (val.arrayValue !== undefined) {
      obj[key] = (val.arrayValue.values || []).map((item: any) => {
        if (item.stringValue !== undefined) return item.stringValue;
        if (item.mapValue !== undefined) return parseFirestoreMap(item.mapValue.fields);
        return item;
      });
    } else if (val.mapValue !== undefined) {
      obj[key] = parseFirestoreMap(val.mapValue.fields);
    }
  }
  return obj;
}

function parseFirestoreMap(fields: any): any {
  if (!fields) return {};
  const map: any = {};
  for (const [key, val] of Object.entries<any>(fields)) {
    if (val.stringValue !== undefined) map[key] = val.stringValue;
    else if (val.integerValue !== undefined) map[key] = parseInt(val.integerValue, 10);
    else if (val.doubleValue !== undefined) map[key] = parseFloat(val.doubleValue);
    else if (val.booleanValue !== undefined) map[key] = val.booleanValue;
    else if (val.arrayValue !== undefined) {
      map[key] = (val.arrayValue.values || []).map((i: any) => i.stringValue || i);
    }
  }
  return map;
}
