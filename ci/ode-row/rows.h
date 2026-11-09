#pragma once
#include <emmintrin.h>

inline __m128 LoadPair(const float* values)
{
    const auto pair = _mm_castsi128_ps(_mm_loadl_epi64(reinterpret_cast<const __m128i*>(values)));
    return _mm_movelh_ps(pair, pair);
}

inline void AccumulateSix(float* forces, const float* inverseJacobian, float delta)
{
    const auto scale = _mm_set1_ps(delta);
    const auto change = _mm_mul_ps(_mm_loadu_ps(inverseJacobian), scale);
    _mm_storeu_ps(forces, _mm_add_ps(change, _mm_loadu_ps(forces)));
    const auto tail = _mm_mul_ps(LoadPair(inverseJacobian + 4), scale);
    _mm_storel_epi64(reinterpret_cast<__m128i*>(forces + 4),
        _mm_castps_si128(_mm_add_ps(tail, LoadPair(forces + 4))));
}

template<int lane>
inline __m128 InFirstLane(__m128 value)
{
    return _mm_shuffle_ps(value, value, _MM_SHUFFLE(lane, lane, lane, lane));
}

inline float DotSix(const float* forces, const float* jacobian)
{
    // Keep the two sums and the rounding order from the played x64 binary.
    const auto low = _mm_mul_ps(_mm_loadu_ps(forces), _mm_loadu_ps(jacobian));
    const auto high = _mm_mul_ps(LoadPair(forces + 4), LoadPair(jacobian + 4));
    const auto first = _mm_add_ss(_mm_add_ss(low, InFirstLane<2>(low)), InFirstLane<1>(low));
    const auto last = _mm_add_ss(_mm_add_ss(high, InFirstLane<1>(high)), InFirstLane<3>(low));
    return _mm_cvtss_f32(_mm_add_ss(last, first));
}
