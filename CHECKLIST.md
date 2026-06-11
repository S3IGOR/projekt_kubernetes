# CHECKLIST — Projekt Kubernetes

Aplikacja TODO: **frontend Nginx** → **backend Python/Flask** → **PostgreSQL**  
Pipeline CI/CD: **GitHub Actions** (build → smoke test na kind → opcjonalny deploy)

> Czas weryfikacji: ~15–20 minut

---

## 0. Wymagania wstępne

| Narzędzie | Minimalna wersja | Instalacja |
| Docker | 24+ | https://docs.docker.com/get-docker/ |
| kind **lub** minikube **lub** k3d | kind ≥ 0.23 | patrz sekcja 1 |
| kubectl | 1.29+ | https://kubernetes.io/docs/tasks/tools/ |
| (opcjonalne) helm | 3+ | https://helm.sh/docs/intro/install/ |

---

## 1. Uruchomienie klastra lokalnego

### 1a. kind (zalecany — używany też w CI)

```bash
# Utwórz klaster z portmappingiem dla Ingressa
cat <<EOF | kind create cluster --name todo --config=-
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    kubeadmConfigPatches:
      - |
        kind: InitConfiguration
        nodeRegistration:
          kubeletExtraArgs:
            node-labels: "ingress-ready=true"
    extraPortMappings:
      - containerPort: 80
        hostPort: 8080
        protocol: TCP
EOF

# Zainstaluj ingress-nginx
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.11.2/deploy/static/provider/kind/deploy.yaml
kubectl wait --namespace ingress-nginx \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller \
  --timeout=120s
```

### 1b. minikube

```bash
minikube start --driver=docker
minikube addons enable ingress
# Aplikacja dostępna pod: $(minikube ip)
```

### 1c. k3d

```bash
k3d cluster create todo -p "8080:80@loadbalancer"
# Ingress controller zawarty w k3d
```

---

## 2. Zasoby Kubernetes w projekcie

| Plik | Rodzaj | Opis |
|------|--------|------|
| `k8s/namespace.yaml` | Namespace | `todo-app` — izolacja wszystkich zasobów |
| `k8s/postgres/secret.yaml` | Secret | Dane logowania do bazy (stringData) |
| `k8s/postgres/pvc.yaml` | PersistentVolumeClaim | 1 Gi trwałego storage dla PostgreSQL |
| `k8s/postgres/deployment.yaml` | Deployment | PostgreSQL 16-alpine, liveness/readiness probe |
| `k8s/postgres/service.yaml` | Service | ClusterIP `postgres:5432` |
| `k8s/backend/deployment.yaml` | Deployment | Flask API, 2 repliki, securityContext, sondy |
| `k8s/backend/service.yaml` | Service | ClusterIP `backend:8080` |
| `k8s/frontend/deployment.yaml` | Deployment | Nginx, 2 repliki, securityContext, sondy |
| `k8s/frontend/service.yaml` | Service | ClusterIP `frontend:80` |
| `k8s/ingress.yaml` | Ingress | `todo.local` → frontend + /api → backend |

**Cechy bezpieczeństwa:**
- `runAsNonRoot: true` + `runAsUser` dla backendu i frontendu
- `allowPrivilegeEscalation: false` + `capabilities: drop: [ALL]`
- `seccompProfile: RuntimeDefault`
- `readOnlyRootFilesystem: true` (backend)

**Limity zasobów:**

| Kontener | CPU req | CPU limit | RAM req | RAM limit |
|----------|---------|-----------|---------|-----------|
| postgres | 100m | 500m | 128Mi | 512Mi |
| backend | 50m | 250m | 64Mi | 256Mi |
| frontend | 20m | 100m | 32Mi | 128Mi |

---

## 3. Budowanie obrazów (lokalnie)

```bash
export OWNER=S3IGOR

docker build -t ghcr.io/$OWNER/todo-backend:latest  ./backend
docker build -t ghcr.io/$OWNER/todo-frontend:latest ./frontend

# Załaduj do kind (jeśli używasz kind)
kind load docker-image ghcr.io/$OWNER/todo-backend:latest  --name todo
kind load docker-image ghcr.io/$OWNER/todo-frontend:latest --name todo
```

---

## 4. manifest i wdróżenie

```bash
export OWNER=S3IGOR

sed -i "s|ghcr.io/OWNER/|ghcr.io/$OWNER/|g" \
  k8s/backend/deployment.yaml \
  k8s/frontend/deployment.yaml

# Dodaj imagePullPolicy: Never dla obrazów załadowanych lokalnie do kind
kubectl patch deployment backend -n todo-app --type=json \
  -p='[{"op":"add","path":"/spec/template/spec/containers/0/imagePullPolicy","value":"Never"}]' \
  2>/dev/null || true

kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/postgres/
kubectl apply -f k8s/backend/
kubectl apply -f k8s/frontend/
kubectl apply -f k8s/ingress.yaml
```

---

## 5. Komendy kubectl — weryfikacja

```bash
# Stan wszystkich zasobów w namespace
kubectl get all -n todo-app

# Oczekuj na gotowość wdrożeń
kubectl rollout status deployment/postgres  -n todo-app
kubectl rollout status deployment/backend   -n todo-app
kubectl rollout status deployment/frontend  -n todo-app

# Sprawdź PVC (Bound = OK)
kubectl get pvc -n todo-app

# Sprawdź Ingress
kubectl get ingress -n todo-app

# Logi backendu
kubectl logs -l app=backend -n todo-app --tail=30

# Opisz pod (sondy, eventy)
kubectl describe pod -l app=backend -n todo-app
```

---

## 6. Przykładowe wyniki kubectl

### `kubectl get all -n todo-app`

```
NAME                            READY   STATUS    RESTARTS   AGE
pod/backend-6d8b7f9c4-kx2qp    1/1     Running   0          2m
pod/backend-6d8b7f9c4-w9s7l    1/1     Running   0          2m
pod/frontend-7c4b5d8f6-j4prt   1/1     Running   0          2m
pod/frontend-7c4b5d8f6-m8vwn   1/1     Running   0          2m
pod/postgres-5f9c6d7b8-xk3ms   1/1     Running   0          3m

NAME               TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)    AGE
service/backend    ClusterIP   10.96.45.12     <none>        8080/TCP   2m
service/frontend   ClusterIP   10.96.112.34    <none>        80/TCP     2m
service/postgres   ClusterIP   10.96.78.90     <none>        5432/TCP   3m

NAME                       READY   UP-TO-DATE   AVAILABLE   AGE
deployment.apps/backend    2/2     2            2           2m
deployment.apps/frontend   2/2     2            2           2m
deployment.apps/postgres   1/1     1            1           3m
```

### `kubectl get pvc -n todo-app`

```
NAME           STATUS   VOLUME                                     CAPACITY   ACCESS MODES   STORAGECLASS   AGE
postgres-pvc   Bound    pvc-a1b2c3d4-e5f6-7890-abcd-ef1234567890   1Gi        RWO            standard       3m
```

### `kubectl get ingress -n todo-app`

```
NAME            CLASS   HOSTS        ADDRESS     PORTS   AGE
todo-ingress    nginx   todo.local   172.18.0.2  80      2m
```

---

## 7. Test manualny aplikacji (kind → port 8080)

```bash
# Health check
curl -s http://localhost:8080/healthz
# {"status":"ok"}

# Readiness check
curl -s http://localhost:8080/readyz
# {"status":"ready"}

# Utwórz zadanie
curl -s -X POST http://localhost:8080/api/todos \
  -H "Content-Type: application/json" \
  -d '{"title":"Sprawdź Kubernetes"}' | python3 -m json.tool
# {
#   "created_at": "2026-05-30T10:00:00.000000+00:00",
#   "done": false,
#   "id": 1,
#   "title": "Sprawdź Kubernetes"
# }

# Wylistuj zadania
curl -s http://localhost:8080/api/todos | python3 -m json.tool

# Oznacz jako ukończone
curl -s -X PATCH http://localhost:8080/api/todos/1 \
  -H "Content-Type: application/json" \
  -d '{"done":true}'

# Frontend — otwórz w przeglądarce:
echo "Otwórz: http://localhost:8080"
# (lub: echo "127.0.0.1 todo.local" >> /etc/hosts && otwórz http://todo.local)
```

---

## 8. Pipeline CI/CD — GitHub Actions

### Jak uruchomić

1. Stwórz repozytorium na GitHub i wypchnij kod:

   ```bash
   git remote add origin https://github.com/S3IGOR/projekt_kubernetes.git
   git push -u origin main
   ```

2. Pipeline uruchamia się automatycznie przy każdym push do `main`.

### Etapy pipeline

| Job | Opis |
| `test` | Instalacja zależności Python, uruchomienie pytest |
| `build` | Build i push obrazów Docker do GHCR (ghcr.io) |
| `smoke` | Klaster kind w CI, deploy, testy HTTP API |
| `deploy` | (opcjonalny) `kubectl set image` na produkcji — wymaga sekretu `KUBECONFIG` |

### Link do ostatniego udanego workflow

> **[GitHub Actions — ostatni udany run](../../actions/workflows/ci-cd.yml)**  
> *(Link aktywny po wypchnięciu repo i uruchomieniu pipeline)*

Bezpośredni URL po skonfigurowaniu repo:  
`https://github.com/S3IGOR/projekt_kubernetes/actions/workflows/ci-cd.yml`

---

## 9. Czyszczenie

```bash
# Usuń namespace (usuwa wszystkie zasoby)
kubectl delete namespace todo-app

# Usuń klaster kind
kind delete cluster --name todo

# Usuń klaster minikube
minikube delete

# Usuń klaster k3d
k3d cluster delete todo
```

---

## 10. Szybka lista kontrolna

- [ ] `kubectl get all -n todo-app` — 5 podów Running
- [ ] `kubectl get pvc -n todo-app` — STATUS = Bound
- [ ] `kubectl get ingress -n todo-app` — wpis widoczny
- [ ] `curl http://localhost:8080/healthz` → `{"status":"ok"}`
- [ ] `curl http://localhost:8080/api/todos` → lista JSON
- [ ] `curl -X POST .../api/todos -d '{"title":"test"}'` → 201 Created
- [ ] Frontend dostępny pod `http://localhost:8080`
- [ ] GitHub Actions — job `smoke` zielony
- [ ] Obrazy w GHCR (zakładka Packages w repo)
- [ ] `kubectl describe pod -l app=backend -n todo-app` — liveness/readiness Probes widoczne
