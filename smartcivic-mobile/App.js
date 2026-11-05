import React, { useState, useEffect } from 'react';
import {
  StyleSheet,
  Text,
  View,
  TextInput,
  TouchableOpacity,
  FlatList,
  Alert,
  Image,
  ActivityIndicator,
  SafeAreaView,
  StatusBar,
  ScrollView,
  RefreshControl,
  Linking,
  Platform
} from 'react-native';
import * as SecureStore from 'expo-secure-store';
import * as ImagePicker from 'expo-image-picker';
import * as Location from 'expo-location';
import api from './src/services/api';

const ROYAL_THEME = {
  bg: '#0a0f2c',           // Royal Navy background
  surface: '#121a45',      // Royal Surface
  surfaceAlt: '#1a2360',   // Royal Card surface
  border: 'rgba(231, 227, 240, 0.14)',
  borderAccent: '#c9a227', // Imperial Gold
  primary: '#6d28d9',      // Royal Purple brand
  primaryDark: '#4c1d95',
  secondary: '#3730a3',    // Royal Indigo
  gold: '#c9a227',         // Imperial Gold accent
  goldLight: '#e7c76a',
  text: '#f3f1ff',         // Royal light text
  textMuted: '#9ba1b8',
  textSecondary: '#cbd5e1',
  ruby: '#d1264a',         // Critical/Logout badge
  emerald: '#0f9d6b',      // Resolved / Success / Nav
  amber: '#d99a1a',        // Warning
  sapphire: '#2f5bd8',     // Info / Action
};

export default function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [userRole, setUserRole] = useState('citizen');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [serverUrl, setServerUrl] = useState(process.env.EXPO_PUBLIC_API_URL || 'http://10.0.2.2:5000/api');

  // App state
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [activeTab, setActiveTab] = useState('tasks');

  // Citizen complaint form state
  const [complaintTitle, setComplaintTitle] = useState('');
  const [complaintDesc, setComplaintDesc] = useState('');
  const [complaintCategory, setComplaintCategory] = useState('road');
  const [selectedPhoto, setSelectedPhoto] = useState(null);

  useEffect(() => {
    checkLoginStatus();
  }, []);

  // Live polling for worker tasks every 30s
  useEffect(() => {
    let interval = null;
    if (isAuthenticated && userRole === 'worker') {
      interval = setInterval(() => {
        fetchTasks(true);
      }, 30000);
    }
    return () => {
      if (interval) clearInterval(interval);
    };
  }, [isAuthenticated, userRole]);

  const checkLoginStatus = async () => {
    try {
      const token = await SecureStore.getItemAsync('user_token');
      const savedRole = await SecureStore.getItemAsync('user_role');
      if (token) {
        setIsAuthenticated(true);
        if (savedRole) setUserRole(savedRole);
        fetchTasks();
      }
    } catch (err) {
      console.log('Error checking login status:', err);
    }
  };

  const handleLogin = async () => {
    if (!username.trim() || !password.trim()) {
      Alert.alert('Validation Error', 'Please enter your username/email and password.');
      return;
    }

    try {
      setLoading(true);
      if (serverUrl && serverUrl.startsWith('http')) {
        api.defaults.baseURL = serverUrl.endsWith('/') ? serverUrl.slice(0, -1) : serverUrl;
      }

      const response = await api.post('/auth/login', {
        email: username,
        username: username,
        password: password
      });

      if (response.data.success || response.data.token) {
        const token = response.data.token || response.data.access_token;
        const role = response.data.role || 'citizen';

        await SecureStore.setItemAsync('user_token', token);
        await SecureStore.setItemAsync('user_role', role);

        setIsAuthenticated(true);
        setUserRole(role);
        Alert.alert('Welcome', `Logged in successfully as ${role}`);
        fetchTasks();
      }
    } catch (error) {
      const errMsg = error.response?.data?.message || error.response?.data?.error?.message || 'Check your credentials or network connection.';
      Alert.alert('Login Failed', errMsg);
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = async () => {
    try {
      await SecureStore.deleteItemAsync('user_token');
      await SecureStore.deleteItemAsync('user_role');
    } catch (e) { }
    setIsAuthenticated(false);
    setTasks([]);
  };

  const fetchTasks = async (silent = false) => {
    try {
      if (!silent) setLoading(true);
      const endpoint = userRole === 'worker' ? '/workers/assigned-tasks' : '/issues';
      const response = await api.get(endpoint);

      const taskList = response.data.tasks || response.data.data || response.data.issues || [];
      setTasks(taskList);
    } catch (error) {
      if (!silent) {
        console.log('Error fetching tasks:', error.message);
      }
    } finally {
      if (!silent) setLoading(false);
      setRefreshing(false);
    }
  };

  const onRefresh = () => {
    setRefreshing(true);
    fetchTasks();
  };

  const handleNavigateToLocation = (lat, lng, address) => {
    const label = encodeURIComponent(address || 'Civic Issue Location');
    const url = Platform.select({
      ios: `maps:0,0?q=${label}@${lat},${lng}`,
      android: `geo:0,0?q=${lat},${lng}(${label})`
    });

    Linking.canOpenURL(url).then((supported) => {
      if (supported) {
        Linking.openURL(url);
      } else {
        Alert.alert('Navigation Coordinates', `Lat: ${lat}, Lng: ${lng}\nAddress: ${address}`);
      }
    }).catch(() => {
      Alert.alert('Navigation Coordinates', `Lat: ${lat}, Lng: ${lng}\nAddress: ${address}`);
    });
  };

  const pickComplaintPhoto = async () => {
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) {
      Alert.alert('Permission Required', 'Photo gallery permission is required.');
      return;
    }

    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      quality: 0.8,
    });

    if (!result.canceled && result.assets[0]) {
      setSelectedPhoto(result.assets[0]);
    }
  };

  const handleSubmitComplaint = async () => {
    if (!complaintDesc.trim() || complaintDesc.trim().length < 10) {
      Alert.alert('Validation Error', 'Description must be at least 10 characters.');
      return;
    }

    try {
      setLoading(true);
      const locPerm = await Location.requestForegroundPermissionsAsync();
      let lat = 12.9716;
      let lng = 77.5946;

      if (locPerm.granted) {
        const currLoc = await Location.getCurrentPositionAsync({});
        lat = currLoc.coords.latitude;
        lng = currLoc.coords.longitude;
      }

      const formData = new FormData();
      formData.append('title', complaintTitle || complaintDesc.substring(0, 30));
      formData.append('description', complaintDesc);
      formData.append('category', complaintCategory);
      formData.append('latitude', lat.toString());
      formData.append('longitude', lng.toString());
      formData.append('ward', 'Ward 1');

      if (selectedPhoto) {
        const filename = selectedPhoto.uri.split('/').pop() || 'complaint.jpg';
        const match = /\.(\w+)$/.exec(filename);
        const type = match ? `image/${match[1]}` : 'image/jpeg';
        formData.append('image', { uri: selectedPhoto.uri, name: filename, type });
      }

      const response = await api.post('/issues', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });

      if (response.data.success) {
        Alert.alert('Success', 'Civic issue report submitted successfully!');
        setComplaintTitle('');
        setComplaintDesc('');
        setSelectedPhoto(null);
        setActiveTab('tasks');
        fetchTasks();
      }
    } catch (error) {
      Alert.alert('Submission Failed', error.response?.data?.message || 'Could not post grievance.');
    } finally {
      setLoading(false);
    }
  };

  const handleResolveTask = async (taskId) => {
    const cameraPerm = await ImagePicker.requestCameraPermissionsAsync();
    const locPerm = await Location.requestForegroundPermissionsAsync();

    if (!cameraPerm.granted || !locPerm.granted) {
      Alert.alert('Permissions Needed', 'Camera and GPS location permissions are required to upload repair proof.');
      return;
    }

    const result = await ImagePicker.launchCameraAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      quality: 0.8,
    });

    if (!result.canceled && result.assets[0]) {
      try {
        setLoading(true);
        const location = await Location.getCurrentPositionAsync({});
        const photo = result.assets[0];

        const formData = new FormData();
        const filename = photo.uri.split('/').pop() || 'resolution.jpg';
        formData.append('after_image', {
          uri: photo.uri,
          name: filename,
          type: 'image/jpeg'
        });
        formData.append('latitude', location.coords.latitude.toString());
        formData.append('longitude', location.coords.longitude.toString());
        formData.append('notes', 'Completed repair work on site via mobile client.');

        const res = await api.post(`/issues/${taskId}/resolve`, formData, {
          headers: { 'Content-Type': 'multipart/form-data' }
        });

        if (res.data.success) {
          Alert.alert('Task Resolved', `Resolution proof submitted! GPS: ${location.coords.latitude.toFixed(4)}, ${location.coords.longitude.toFixed(4)}`);
          fetchTasks();
        }
      } catch (err) {
        Alert.alert('Upload Error', err.response?.data?.message || 'Failed to submit resolution proof.');
      } finally {
        setLoading(false);
      }
    }
  };

  if (!isAuthenticated) {
    return (
      <SafeAreaView style={styles.darkContainer}>
        <StatusBar barStyle="light-content" backgroundColor={ROYAL_THEME.bg} />
        <ScrollView contentContainerStyle={styles.loginContent}>
          <Text style={styles.brandTitle}>SmartCivic v2</Text>
          <Text style={styles.brandSubtitle}>Standalone Mobile App Client</Text>

          <View style={styles.card}>
            <Text style={styles.inputLabel}>Backend API Server Endpoint</Text>
            <TextInput
              style={styles.input}
              value={serverUrl}
              onChangeText={setServerUrl}
              placeholder="http://YOUR_LOCAL_IP:5000/api"
              placeholderTextColor="#64748B"
              autoCapitalize="none"
            />

            <Text style={styles.inputLabel}>Username or Email</Text>
            <TextInput
              style={styles.input}
              placeholder="e.g. uat_citizen@smartcivic.com"
              placeholderTextColor="#64748B"
              value={username}
              onChangeText={setUsername}
              autoCapitalize="none"
            />

            <Text style={styles.inputLabel}>Password</Text>
            <TextInput
              style={styles.input}
              placeholder="••••••••"
              placeholderTextColor="#64748B"
              secureTextEntry
              value={password}
              onChangeText={setPassword}
            />

            <TouchableOpacity style={styles.primaryButton} onPress={handleLogin} disabled={loading}>
              {loading ? (
                <ActivityIndicator color="#FFF" />
              ) : (
                <Text style={styles.buttonText}>Log In to SmartCivic</Text>
              )}
            </TouchableOpacity>
          </View>
        </ScrollView>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.darkContainer}>
      <StatusBar barStyle="light-content" backgroundColor={ROYAL_THEME.bg} />

      {/* Header */}
      <View style={styles.header}>
        <View>
          <Text style={styles.headerTitle}>
            {userRole === 'worker' ? 'Field Worker Route Planner' : 'SmartCivic Mobile'}
          </Text>
          <Text style={styles.headerSubtitle}>Role: {userRole.toUpperCase()}</Text>
        </View>
        <TouchableOpacity style={styles.logoutBadge} onPress={handleLogout}>
          <Text style={styles.logoutText}>Logout</Text>
        </TouchableOpacity>
      </View>

      {/* Tabs for Citizen */}
      {userRole !== 'worker' && (
        <View style={styles.tabContainer}>
          <TouchableOpacity
            style={[styles.tabButton, activeTab === 'tasks' && styles.tabActive]}
            onPress={() => setActiveTab('tasks')}
          >
            <Text style={[styles.tabText, activeTab === 'tasks' && styles.tabTextActive]}>Track Issues</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.tabButton, activeTab === 'report' && styles.tabActive]}
            onPress={() => setActiveTab('report')}
          >
            <Text style={[styles.tabText, activeTab === 'report' && styles.tabTextActive]}>Report Issue</Text>
          </TouchableOpacity>
        </View>
      )}

      {/* Content */}
      {activeTab === 'report' && userRole !== 'worker' ? (
        <ScrollView style={styles.scrollForm}>
          <View style={styles.card}>
            <Text style={styles.cardHeaderTitle}>File New Civic Grievance</Text>

            <Text style={styles.inputLabel}>Issue Title</Text>
            <TextInput
              style={styles.input}
              placeholder="e.g. Deep pothole near main cross road"
              placeholderTextColor="#64748B"
              value={complaintTitle}
              onChangeText={setComplaintTitle}
            />

            <Text style={styles.inputLabel}>Description</Text>
            <TextInput
              style={[styles.input, { height: 90 }]}
              placeholder="Provide detailed description for AI classification..."
              placeholderTextColor="#64748B"
              multiline
              value={complaintDesc}
              onChangeText={setComplaintDesc}
            />

            <Text style={styles.inputLabel}>Category</Text>
            <View style={styles.categoryRow}>
              {['road', 'water', 'electricity', 'sanitation', 'drainage'].map((cat) => (
                <TouchableOpacity
                  key={cat}
                  style={[styles.catChip, complaintCategory === cat && styles.catChipActive]}
                  onPress={() => setComplaintCategory(cat)}
                >
                  <Text style={[styles.catText, complaintCategory === cat && styles.catTextActive]}>
                    {cat.toUpperCase()}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>

            <TouchableOpacity style={styles.secondaryButton} onPress={pickComplaintPhoto}>
              <Text style={styles.secondaryButtonText}>
                {selectedPhoto ? '✓ Photo Selected' : '📷 Add Before Photo'}
              </Text>
            </TouchableOpacity>

            <TouchableOpacity style={styles.primaryButton} onPress={handleSubmitComplaint} disabled={loading}>
              {loading ? <ActivityIndicator color="#FFF" /> : <Text style={styles.buttonText}>Submit Complaint</Text>}
            </TouchableOpacity>
          </View>
        </ScrollView>
      ) : (
        <FlatList
          data={tasks}
          keyExtractor={(item, index) => item.id || item.issue_id || item._id || index.toString()}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={ROYAL_THEME.gold} />}
          renderItem={({ item }) => {
            const lat = item.location?.latitude || item.location?.coordinates?.[1] || 12.9716;
            const lng = item.location?.longitude || item.location?.coordinates?.[0] || 77.5946;
            const addr = item.location?.address || item.address || 'Bengaluru';
            const fixType = item.fix_type || item.type || 'Standard Repair';

            return (
              <View style={styles.taskCard}>
                <View style={styles.taskHeader}>
                  <Text style={styles.categoryTitle}>{item.category?.toUpperCase() || 'CIVIC ISSUE'}</Text>
                  <Text style={styles.badgePriority}>{item.priority?.toUpperCase() || item.severity?.toUpperCase() || 'MEDIUM'}</Text>
                </View>

                <Text style={styles.textLine}><Text style={styles.boldText}>Fix Required:</Text> {fixType}</Text>
                <Text style={styles.textLine}><Text style={styles.boldText}>Description:</Text> {item.description || 'No description provided.'}</Text>
                <Text style={styles.textLine}><Text style={styles.boldText}>Location:</Text> {addr}</Text>
                <Text style={styles.textLine}><Text style={styles.boldText}>Status:</Text> <Text style={styles.statusHighlight}>{item.status}</Text></Text>

                <TouchableOpacity
                  style={styles.navButton}
                  onPress={() => handleNavigateToLocation(lat, lng, addr)}
                >
                  <Text style={styles.buttonText}>🧭 Navigate to Location</Text>
                </TouchableOpacity>

                {userRole === 'worker' && item.status !== 'closed' && (
                  <TouchableOpacity style={styles.resolveButton} onPress={() => handleResolveTask(item.id || item._id)}>
                    <Text style={styles.buttonText}>📸 Capture Resolution Proof</Text>
                  </TouchableOpacity>
                )}
              </View>
            );
          }}
          ListEmptyComponent={
            <View style={styles.emptyContainer}>
              <Text style={styles.emptyText}>No active routes assigned by admin.</Text>
            </View>
          }
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  darkContainer: { flex: 1, backgroundColor: ROYAL_THEME.bg, paddingHorizontal: 16 },
  loginContent: { flexGrow: 1, justifyContent: 'center', paddingVertical: 40 },
  brandTitle: { fontSize: 32, fontWeight: '800', color: ROYAL_THEME.gold, textAlign: 'center', letterSpacing: -0.5 },
  brandSubtitle: { fontSize: 13, color: ROYAL_THEME.textMuted, textAlign: 'center', marginBottom: 24, textTransform: 'uppercase', letterSpacing: 1.5 },
  card: { backgroundColor: ROYAL_THEME.surface, borderRadius: 16, padding: 20, borderWidth: 1, borderColor: ROYAL_THEME.border, borderTopWidth: 3, borderTopColor: ROYAL_THEME.gold },
  cardHeaderTitle: { fontSize: 20, fontWeight: '700', color: ROYAL_THEME.text, marginBottom: 16 },
  inputLabel: { fontSize: 12, fontWeight: '700', color: ROYAL_THEME.goldLight, marginBottom: 6, marginTop: 12, textTransform: 'uppercase', letterSpacing: 0.5 },
  input: { backgroundColor: ROYAL_THEME.bg, color: ROYAL_THEME.text, paddingHorizontal: 14, paddingVertical: 12, borderRadius: 10, borderWidth: 1, borderColor: 'rgba(201, 162, 39, 0.25)', fontSize: 15 },
  primaryButton: { backgroundColor: ROYAL_THEME.primary, paddingVertical: 14, borderRadius: 10, alignItems: 'center', marginTop: 20, borderWidth: 1, borderColor: ROYAL_THEME.gold },
  buttonText: { color: '#FFF', fontWeight: '700', fontSize: 15 },
  secondaryButton: { backgroundColor: ROYAL_THEME.surfaceAlt, paddingVertical: 12, borderRadius: 10, alignItems: 'center', marginTop: 16, borderWidth: 1, borderColor: 'rgba(201, 162, 39, 0.3)' },
  secondaryButtonText: { color: ROYAL_THEME.goldLight, fontWeight: '600' },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: 16, borderBottomWidth: 1, borderBottomColor: 'rgba(201, 162, 39, 0.25)' },
  headerTitle: { fontSize: 20, fontWeight: '800', color: ROYAL_THEME.text },
  headerSubtitle: { fontSize: 12, color: ROYAL_THEME.gold, fontWeight: '700', textTransform: 'uppercase', letterSpacing: 0.5 },
  logoutBadge: { backgroundColor: ROYAL_THEME.ruby, paddingHorizontal: 12, paddingVertical: 6, borderRadius: 8 },
  logoutText: { color: '#FFF', fontSize: 12, fontWeight: '700' },
  tabContainer: { flexDirection: 'row', backgroundColor: ROYAL_THEME.surface, borderRadius: 12, padding: 4, marginVertical: 12, borderWidth: 1, borderColor: ROYAL_THEME.border },
  tabButton: { flex: 1, paddingVertical: 10, alignItems: 'center', borderRadius: 8 },
  tabActive: { backgroundColor: ROYAL_THEME.primary, borderWidth: 1, borderColor: ROYAL_THEME.gold },
  tabText: { color: ROYAL_THEME.textMuted, fontWeight: '600' },
  tabTextActive: { color: '#FFF' },
  categoryRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 6 },
  catChip: { backgroundColor: ROYAL_THEME.surfaceAlt, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 6, borderWidth: 1, borderColor: ROYAL_THEME.border },
  catChipActive: { backgroundColor: ROYAL_THEME.primary, borderColor: ROYAL_THEME.gold },
  catText: { color: ROYAL_THEME.textMuted, fontSize: 11, fontWeight: '600' },
  catTextActive: { color: ROYAL_THEME.goldLight },
  taskCard: { backgroundColor: ROYAL_THEME.surface, borderRadius: 12, padding: 16, marginVertical: 8, borderWidth: 1, borderColor: ROYAL_THEME.border, borderLeftWidth: 3, borderLeftColor: ROYAL_THEME.gold },
  taskHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 },
  categoryTitle: { fontSize: 18, fontWeight: '800', color: ROYAL_THEME.goldLight },
  badgePriority: { backgroundColor: ROYAL_THEME.ruby, color: '#FFF', fontSize: 10, fontWeight: '800', paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6, overflow: 'hidden' },
  textLine: { color: ROYAL_THEME.textSecondary, fontSize: 14, marginBottom: 4 },
  boldText: { fontWeight: '700', color: ROYAL_THEME.text },
  statusHighlight: { color: ROYAL_THEME.gold, fontWeight: '700' },
  navButton: { backgroundColor: ROYAL_THEME.emerald, paddingVertical: 10, borderRadius: 8, alignItems: 'center', marginTop: 10 },
  resolveButton: { backgroundColor: ROYAL_THEME.primary, paddingVertical: 10, borderRadius: 8, alignItems: 'center', marginTop: 8, borderWidth: 1, borderColor: ROYAL_THEME.gold },
  scrollForm: { flex: 1, marginTop: 8 },
  emptyContainer: { alignItems: 'center', marginTop: 60 },
  emptyText: { color: ROYAL_THEME.textMuted, fontSize: 15 }
});
