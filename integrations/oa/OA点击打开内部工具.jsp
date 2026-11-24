<%@ page language="java" contentType="text/html; charset=UTF-8" pageEncoding="UTF-8" trimDirectiveWhitespaces="true" %>
    <%@ page import="com.landray.kmss.util.UserUtil" %>
        <%-- Author: liuzhiwei_jn; Date: 2026-11-19; Version: v1.0.6 --%>
            <%! private static String boyuanConfig(String name, String fallback) { String
                value=System.getProperty(name); if (value==null || value.trim().isEmpty()) value=System.getenv(name);
                return value==null || value.trim().isEmpty() ? fallback : value.trim(); } private static String
                boyuanBase64(byte[] value) { final char[]
                alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" .toCharArray();
                StringBuilder encoded=new StringBuilder((value.length * 4 + 2) / 3); for (int i=0; i < value.length; i
                +=3) { int bytes=(value[i] & 0xff) << 16; if (i + 1 < value.length) bytes |=(value[i + 1] & 0xff) << 8;
                if (i + 2 < value.length) bytes |=value[i + 2] & 0xff; encoded.append(alphabet[(bytes>>> 18) & 63]);
                encoded.append(alphabet[(bytes >>> 12) & 63]);
                if (i + 1 < value.length) encoded.append(alphabet[(bytes>>> 6) & 63]);
                    if (i + 2 < value.length) encoded.append(alphabet[bytes & 63]); } return encoded.toString(); }
                        private static String boyuanSignedQuery(String phone, String secret, String audience, long
                        issued, int ttl, String nonce) throws Exception { return boyuanSignedQuery(phone, secret,
                        audience, issued, ttl, nonce, null); } private static String boyuanSignedQuery(String phone,
                        String secret, String audience, long issued, int ttl, String nonce, String next) throws
                        Exception { if (!phone.matches("1[3-9][0-9]{9}")) throw new
                        IllegalArgumentException("OA_LOGIN_NAME_FORMAT"); if (!audience.matches("[A-Za-z0-9._-]{1,80}"))
                        throw new IllegalArgumentException("AUDIENCE_FORMAT"); if (!nonce.matches("[0-9a-f]{32}")) throw
                        new IllegalArgumentException("NONCE_FORMAT"); if (secret.getBytes("UTF-8").length < 32) throw
                        new IllegalArgumentException("SECRET_LENGTH"); if (ttl < 1 || ttl> 300) throw new
                        IllegalArgumentException("TTL_RANGE");
                        if (next != null &&
                        !next.matches("/\\?view=stock-orders&stockOrder=[1-9][0-9]{0,9}&stockOrderMode=edit"))
                        throw new IllegalArgumentException("NEXT_PATH_FORMAT");
                        String json = "{\"v\":1,\"phone\":\"" + phone + "\",\"iat\":" + issued
                        + ",\"exp\":" + (issued + ttl) + ",\"nonce\":\"" + nonce + "\",\"aud\":\"" + audience + "\""
                        + (next == null ? "" : ",\"next\":\"" + next + "\"") + "}";
                        String payload = boyuanBase64(json.getBytes("UTF-8"));
                        javax.crypto.Mac mac = javax.crypto.Mac.getInstance("HmacSHA256");
                        mac.init(new javax.crypto.spec.SecretKeySpec(secret.getBytes("UTF-8"), "HmacSHA256"));
                        return "payload=" + payload + "&signature=" +
                        boyuanBase64(mac.doFinal(payload.getBytes("US-ASCII")));
                        }
                        %>
                        <% response.setHeader("Cache-Control", "no-store, no-cache, must-revalidate" );
                            response.setHeader("Pragma", "no-cache" );
                            response.setHeader("Referrer-Policy", "no-referrer" ); String boyuanStage="OA用户信息" ; try {
                            if (UserUtil.getUser()==null) { response.setStatus(401); out.write("请先登录 OA，再点击本系统入口。");
                            return; } String phone=UserUtil.getUser().getFdLoginName(); if (phone==null) throw new
                            IllegalArgumentException("Missing OA phone"); // 在下方引号内填写密钥，须与本系统 .env 的
                            BOYUAN_OA_SSO_SECRET 完全一致，至少 32 字节。 String
                            secret="O4FHI-GIBgKiVdKb8OBAL1vjOX-K7OwxqIuI1GP1uNJaL2ievj_EfQwDfe7wPQn2" ; String
                            audience=boyuanConfig("BOYUAN_OA_SSO_AUDIENCE", "boyuan-internal-tools" ); int
                            ttl=Integer.parseInt(boyuanConfig("BOYUAN_OA_SSO_MAX_AGE", "60" )); // 填写本系统 HTTP 或 HTTPS
                            入口，例如 http://公网IP:端口/auth/oa。 String target="http://36.139.172.238:3599/auth/oa" ;
                            boyuanStage="入口地址" ; java.net.URI targetUri=new java.net.URI(target); if
                            ((!"https".equalsIgnoreCase(targetUri.getScheme()) &&
                            !"http".equalsIgnoreCase(targetUri.getScheme())) || targetUri.getHost()==null ||
                            targetUri.getUserInfo() !=null || targetUri.getRawQuery() !=null ||
                            targetUri.getRawFragment() !=null || !"/auth/oa".equals(targetUri.getPath())) { throw new
                            IllegalArgumentException("Invalid OA target URL"); } boyuanStage="生成随机值" ; byte[] random=new
                            byte[16]; new java.security.SecureRandom().nextBytes(random); StringBuilder nonce=new
                            StringBuilder(); for (byte value : random) nonce.append(String.format("%02x", value &
                            0xff)); boyuanStage="生成签名" ; String stockOrder=request.getParameter("stockOrder"); String
                            mode=request.getParameter("mode"); String next=null; if (stockOrder !=null || mode !=null) {
                            if (stockOrder==null || !stockOrder.matches("[1-9][0-9]{0,9}") || !"edit".equals(mode) ||
                            request.getParameterValues("stockOrder").length !=1 ||
                            request.getParameterValues("mode").length !=1) { throw new IllegalArgumentException("Invalid
                            stock order destination"); } next="/?view=stock-orders&stockOrder=" + stockOrder
                            + "&stockOrderMode=edit" ; } String query=boyuanSignedQuery(phone.trim(), secret, audience,
                            System.currentTimeMillis() / 1000L, ttl, nonce.toString(), next); boyuanStage="跳转" ;
                            response.sendRedirect(targetUri.toASCIIString() + "?" + query); return; } catch (Exception
                            error) { application.log("Boyuan OA login failed at " + boyuanStage + " : " + error.getClass().getName());
        response.setStatus(503);
        out.write(" OA 登录暂不可用，请联系管理员检查入口配置。失败阶段：" + boyuanStage + "；错误类型：" + error.getClass().getSimpleName()); if
                            (error instanceof IllegalArgumentException) { String code=error.getMessage(); if
                            ("OA_LOGIN_NAME_FORMAT".equals(code)) out.write("；原因：OA 登录名不是 11 位大陆手机号"); else if
                            ("AUDIENCE_FORMAT".equals(code)) out.write("；原因：目标系统标识格式不正确"); else if
                            ("NONCE_FORMAT".equals(code)) out.write("；原因：随机值格式不正确"); else if
                            ("SECRET_LENGTH".equals(code)) out.write("；原因：密钥不足 32 字节"); else if
                            ("TTL_RANGE".equals(code)) out.write("；原因：有效期不在 1 到 300 秒之间"); } } %>