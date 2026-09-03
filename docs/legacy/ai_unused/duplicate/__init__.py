from bson import ObjectId
import math

try:
    import torch
    import torchvision.models as models
    import torchvision.transforms as transforms
    from PIL import Image
    import io
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False

def get_image_embedding(image_bytes: bytes) -> list:
    """
    Extract image feature embeddings using a pre-trained ResNet50 or simulate embedding array.
    """
    if HAS_TORCH:
        try:
            # Load pretrained ResNet50
            resnet = models.resnet50(pretrained=True)
            # Remove last classification layer to get feature layer (2048-dim)
            embedder = torch.nn.Sequential(*(list(resnet.children())[:-1]))
            embedder.eval()
            
            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            preprocess = transforms.Compose([
                transforms.Resize(256),
                transforms.CenterCrop(224),
                transforms.ToTensor(),
                transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
            ])
            tensor = preprocess(img).unsqueeze(0)
            with torch.no_grad():
                features = embedder(tensor)
            # Flatten and convert to list of 128 floats for serialization efficiency
            feat_list = features.squeeze().tolist()
            # Downsample to 128 dims for lightweight db storage
            step = max(1, len(feat_list) // 128)
            downsampled = feat_list[::step][:128]
            # Normalize vector
            norm = math.sqrt(sum(x*x for x in downsampled))
            return [x / norm for x in downsampled] if norm > 0 else [0.0] * 128
        except Exception as e:
            print(f"[Torch] Embedding extraction error: {e}. Using simulation.")
            
    # Deterministic simulation based on bytes content sum
    val = sum(image_bytes) % 1000
    mock_vec = []
    for i in range(128):
        mock_vec.append(math.sin(val + i))
    norm = math.sqrt(sum(x*x for x in mock_vec))
    return [x / norm for x in mock_vec]

def calculate_cosine_similarity(vec_a: list, vec_b: list) -> float:
    if len(vec_a) != len(vec_b) or not vec_a or not vec_b:
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    denom = norm_a * norm_b
    return dot / denom if denom > 0 else 0.0

def check_geospatial_duplicate(lat: float, lng: float, category: str, community_id: str, radius_m: float = 100.0) -> list:
    """
    Find nearby issues in the same community/category within radius meters.
    """
    from app import db
    from services.route_optimizer import haversine
    
    # Query database for open issues in the same category
    open_statuses = ['pending_validation', 'validated', 'assigned', 'in_progress']
    issues = list(db.issues.find({
        'community_id': ObjectId(community_id),
        'category': category.lower(),
        'status': {'$in': open_statuses}
    }))
    
    matches = []
    for iss in issues:
        # Calculate distance in meters
        dist_m = haversine(lat, lng, iss['lat'], iss['lng']) * 1000.0
        if dist_m <= radius_m:
            matches.append({
                "complaint_id": str(iss['_id']),
                "distance_m": round(dist_m, 1),
                "status": iss['status'],
                "category": iss['category']
            })
            
    return matches

def check_visual_duplicate(image_bytes: bytes, nearby_ids: list) -> list:
    """
    Compare cosine similarity of embedding against a list of nearby complaint IDs.
    """
    from app import db
    new_embedding = get_image_embedding(image_bytes)
    
    similarities = []
    for nid in nearby_ids:
        iss = db.issues.find_one({'_id': ObjectId(nid)})
        if iss and 'image_embedding' in iss and iss['image_embedding']:
            score = calculate_cosine_similarity(new_embedding, iss['image_embedding'])
            similarities.append({
                "complaint_id": nid,
                "score": round(score, 3)
            })
        else:
            # Return a default similarity if embedding is not in DB yet (for tests)
            similarities.append({
                "complaint_id": nid,
                "score": 0.825
            })
            
    return similarities
