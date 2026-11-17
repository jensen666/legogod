// lego_geometry.dart 的 part 文件：三维向量与轴对齐包围盒（纯 Dart，不依赖 vector_math）。
part of 'lego_geometry.dart';

/// 三维向量（纯 Dart 实现，不依赖 vector_math）。
class Vec3 {
  const Vec3(this.x, this.y, this.z);

  /// 零向量。
  static const Vec3 zero = Vec3(0, 0, 0);

  /// X 分量。
  final double x;

  /// Y 分量（向上）。
  final double y;

  /// Z 分量。
  final double z;

  Vec3 operator +(Vec3 other) => Vec3(x + other.x, y + other.y, z + other.z);

  Vec3 operator -(Vec3 other) => Vec3(x - other.x, y - other.y, z - other.z);

  Vec3 operator *(double scale) => Vec3(x * scale, y * scale, z * scale);

  /// 点积。
  double dot(Vec3 other) => x * other.x + y * other.y + z * other.z;

  /// 叉积。
  Vec3 cross(Vec3 other) => Vec3(
    y * other.z - z * other.y,
    z * other.x - x * other.z,
    x * other.y - y * other.x,
  );

  /// 向量长度。
  double get length => math.sqrt(x * x + y * y + z * z);

  /// 单位化（零向量返回零向量，绝不抛异常）。
  Vec3 get normalized {
    final len = length;
    return len < 1e-9 ? Vec3.zero : Vec3(x / len, y / len, z / len);
  }

  @override
  String toString() => 'Vec3($x, $y, $z)';

  @override
  bool operator ==(Object other) =>
      other is Vec3 && other.x == x && other.y == y && other.z == z;

  @override
  int get hashCode => Object.hash(x, y, z);
}

/// 轴对齐包围盒（空盒用 ±infinity 表示，`isEmpty` 为真）。
class Bounds {
  const Bounds(this.min, this.max);

  /// 空包围盒。
  static const Bounds empty = Bounds(
    Vec3(double.infinity, double.infinity, double.infinity),
    Vec3(
      double.negativeInfinity,
      double.negativeInfinity,
      double.negativeInfinity,
    ),
  );

  /// 最小角。
  final Vec3 min;

  /// 最大角。
  final Vec3 max;

  /// 是否没有包含任何点。
  bool get isEmpty => min.x > max.x || min.y > max.y || min.z > max.z;

  /// 中心点（空盒返回零向量）。
  Vec3 get center => isEmpty
      ? Vec3.zero
      : Vec3((min.x + max.x) / 2, (min.y + max.y) / 2, (min.z + max.z) / 2);

  /// 尺寸（空盒返回零向量）。
  Vec3 get size =>
      isEmpty ? Vec3.zero : Vec3(max.x - min.x, max.y - min.y, max.z - min.z);

  /// 外接球半径（空盒返回 0）。
  double get radius {
    if (isEmpty) return 0;
    final extent = size;
    return 0.5 *
        math.sqrt(
          extent.x * extent.x + extent.y * extent.y + extent.z * extent.z,
        );
  }

  /// 合并另一个包围盒。
  Bounds union(Bounds other) {
    if (other.isEmpty) return this;
    if (isEmpty) return other;
    return Bounds(
      Vec3(
        math.min(min.x, other.min.x),
        math.min(min.y, other.min.y),
        math.min(min.z, other.min.z),
      ),
      Vec3(
        math.max(max.x, other.max.x),
        math.max(max.y, other.max.y),
        math.max(max.z, other.max.z),
      ),
    );
  }

  /// 扩展以包含一个点。
  Bounds include(Vec3 point) => Bounds(
    Vec3(
      math.min(min.x, point.x),
      math.min(min.y, point.y),
      math.min(min.z, point.z),
    ),
    Vec3(
      math.max(max.x, point.x),
      math.max(max.y, point.y),
      math.max(max.z, point.z),
    ),
  );

  @override
  String toString() => 'Bounds(min: $min, max: $max)';
}
