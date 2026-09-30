# SharpTimer Ranking API

API independiente de solo lectura sobre la BD MariaDB de SharpTimer. Única fuente de
las consultas de ranking (`/top`, `/rank`, `/maptop`, `/pb`, `/maps`) — el bot de
Discord ([sharptimer-discord-bot](https://github.com/josesilvaruiz/sharptimer-discord-bot))
y la landing page la consumen por HTTP en vez de tocar la base de datos cada uno por
su lado.

Todos los endpoints son `GET` y requieren el header `X-Api-Key`.

## Despliegue

`k8s/ranking-api.yaml` no incluye el `Secret` (contiene `DB_PASSWORD` y `API_KEY`) —
se crea una sola vez a mano en el cluster y no se vuelve a tocar desde el workflow:

```bash
kubectl create secret generic ranking-api-secrets -n ranking-api \
  --from-literal=DB_PASSWORD='...' \
  --from-literal=API_KEY='...'
```

El resto (namespace, ConfigMap con el script, Deployment, Service) lo gestiona
`.github/workflows/deploy.yml` en cada push a `master`.

Requiere los secrets de repo `SSH_HOST`, `SSH_USER` y `SSH_PRIVATE_KEY_B64` (clave
privada en base64) con acceso SSH al servidor que corre el cluster k3s.

## Cómo alcanzarla desde otro pod del cluster

El Deployment corre con `hostNetwork: true` (necesario porque MariaDB solo escucha en
`127.0.0.1` del host). Esto rompe el Service `ranking-api` (ClusterIP) como vía de acceso
desde OTROS pods normales (no hostNetwork): kube-router hace hairpin NAT y la conexión
vuelve con `ECONNREFUSED`, aunque el Service y sus Endpoints se vean correctos. Un pod
hostNetwork sí puede llegar por el Service sin problema (es la dirección contraria);
el problema es de un pod normal hacia un backend hostNetwork.

**Desde un pod normal del cluster, usa la IP real del nodo, no el Service:**
`http://<IP-del-nodo>:8088`. Es lo que usa la landing (configurado vía `RANKING_API_URL`
en el propio Deployment, no en este repo).

**Desde el propio host** (p.ej. el bot de Discord, que corre como systemd fuera del
cluster): `http://127.0.0.1:8088` funciona sin este problema.
